# Two LLM assistant ideas: a concept assistant and a hand-calc assistant (2026-09-28)

**Status: idea only. Researched and estimated on 2026-09-28. Not planned, not specified, not
started.** Nothing here is a decision. Every choice below is left for the owner, and each one
lists the recommended option first.

- **What was researched.** Two ideas the owner raised on 2026-09-28: an LLM CAD assistant that
  helps with ideas and concepts (Part 1), and a hand-calculation assistant that works on loads in
  the open assembly (Part 2). Part 3 says how the two relate. The open questions for the owner are
  at the end.
- **Baseline.** The research was read-only, at `main` a8a8a09. SOLIDWORKS was never started (this
  machine has no licence), and the installed 2024 SP5 interop was only reflected as metadata. So
  "present" below means an API member exists. It does not mean the member behaves as expected on
  the seat.
- **How to resume.**
  1. Re-read this file and check what changed after a8a8a09: 004's seat probes, the 008-013
     sitting results, and any owner answers.
  2. Answer the open questions at the end.
  3. If the scope changes, amend the constitution first (`/speckit-constitution`, amendment
     1.1.0 to 1.2.0; see sections 1.7 and 2.7).
  4. Run `/speckit-specify` with the chosen part of this file as the description. The next free
     feature number is **014**; 012 stays reserved for drawing creation. Whichever idea starts
     first takes 014, and the other takes 015.
  5. Then run `/speckit-clarify`, `/speckit-plan`, `/speckit-tasks` and `/speckit-analyze` before
     `/speckit-implement`.
- **This file:** `docs/future/llm-assistants-2026-09-28.md`, linked from
  `docs/roadmap-2026-09-22.md` under "Later: researched ideas".

**How to read the estimates.**

| Unit | Meaning |
|---|---|
| Wave | One batch of offline, agent-built work, about one owner-day. |
| Sitting | One session on the licensed pilot seat. |
| Engineer-week | A traditional team's pace, given for comparison. |

Waves and sittings are the agent-assisted pace this repo has shown: 493 commits and 12 spec
packages between 2026-09-12 and 2026-09-27. That pace shortens coding time. It does not shorten
seat time or owner decisions. Every range carries a confidence. "Inferred" marks a judgement that
no source verified.

## Contents

- [Part 1. The LLM CAD assistant for ideas and concepts](#part-1-the-llm-cad-assistant-for-ideas-and-concepts)
- [Part 2. The hand-calc assistant](#part-2-the-hand-calc-assistant)
- [Part 3. How the two relate](#part-3-how-the-two-relate)
- [Open questions for the owner](#open-questions-for-the-owner)

---

## Part 1. The LLM CAD assistant for ideas and concepts

### 1.1 The question, as the owner asked it

> How could we turn this into a general purpose llm CAD assistant for ideating solutions and
> approaches and creating concepts in CAD that could interact with existing designs. Don't
> implement, just estimate the difficulty for an MVP etc

Four research tracks answered it:
- reuse: what carries over from smart_SW;
- sw-api: what the SOLIDWORKS 2024 SP5 API can do;
- state of the art;
- MVP options.

A skeptic's pass then corrected their claims and re-estimated their figures. **The estimates in
this part are the skeptic's adjusted figures** unless a row says otherwise.

### 1.2 The verdict

- **General-purpose ideation is achievable now, and it only reads.** The model reasons about
  approaches, grounded in the open assembly: its interfaces, its free space and its bought parts.
  Code computes every number. This needs a small scope amendment and no write path.
- **General-purpose geometry creation is not an MVP.** Two things rule it out:
  - The measured benchmarks. No model reliably places a part against existing geometry. The
    best exact joint recovery is 23.3% or less.
  - The constitution. It bans generic code execution, which is how research systems generate CAD
    (the model writes CadQuery or FreeCAD code).
- **The API is not the blocker.** Every creation surface a machine builder needs is present on
  2024 SP5. The hard parts are:
  - how the model points at geometry;
  - long positional signatures, for example FeatureExtrusion3 with 23 parameters and HoleWizard5
    with 27;
  - the application thread: modal dialogs, void returns, and dimensioning only on a visible
    document.

  So the model must never call the raw API. It proposes a small typed plan, and a deterministic
  executor applies it. That is the pattern the re-modeler (004) already built.
- **When creation comes, it should use the narrowest write path first:** template copy-and-drive
  on 004's machinery. Native feature creation plus placement with mates costs about 24-40
  engineer-weeks and is bound to the seat.

### 1.3 State of the art

#### Shipped products (fetched 2026-09-28)

| Product | What it does with existing designs | Why it does not fit this owner today | Sources (dates) |
|---|---|---|---|
| SOLIDWORKS LEO, AURA and MARIE (Dassault) | LEO beta skills: Assembly Structure Generator (placeholder files, no geometry), What's Wrong, Design Change Impact and Design Inspection (April 2026 beta), Assembly Performance Doctor (FD03, 2026-07-11: converts modelled threads to cosmetic, makes SpeedPak configurations, writes VBA macros), image to mesh, and BREP to parametric. The 2027 beta roadmap adds parts from sketches and assemblies from prompts. No measured results, only demos. | Needs SOLIDWORKS Design 2026 connected to 3DEXPERIENCE: SP3 or later per Dassault, SP1 per a reseller. It runs on tokens. Everything was beta as of 2026-07-11. One reseller says BREP to parametric works worst on sheet metal and weldments. Not available on the 2024 SP5 desktop seat. | solidsolutions.co.uk/ai-in-solidworks (2026-04-10); blogs.solidworks.com (2026-04-13, 2026-08-13); goengineer.com/blog/ai-in-solidworks (2026-08-10); hawkridgesys.com (2026-07-13, updated 2026-09-02) |
| Autodesk Fusion MCP, Neural CAD | Fusion MCP drives a live Fusion session: it creates, modifies and inspects geometry and runs scripts. Neural CAD (AU 2025) generates editable B-rep. Only AutoConstrain has shipped, and it "cannot yet guarantee perfect precision". AU 2026 announced no generally available geometry generation. | Fusion only. Sources conflict on whether the MCP servers are generally available or a tech preview. | engineering.com (2026-04-22); develop3d.com (2026-09-08); aps.autodesk.com (2026-09-15) |
| Onshape AI Advisor; Adam for Onshape | The Advisor gives help. Agents that edit geometry are on the roadmap only (2026-03-19). Adam (open beta, 2026-03-04) cleans up feature trees, the same job as 004 stage 1. | Onshape only. Adam's planned SOLIDWORKS support is not verified. | onshape.com blog (2026-03-19, 2026-03-04) |
| Siemens Solid Edge 2026 | The Design Copilot is a support chatbot. Magnetic Snap auto-constrains a part dragged into an assembly. Automated drawings. | Makes no 3D geometry. | engineering.com (2026-06-24) |
| Zoo (ML-ephant, Zookeeper) | Generates B-rep plus KCL code. Zookeeper (2026-02-05) edits existing KCL models and checks each change with four-view snapshots. $0-99 a month. | Its own kernel and language, not SOLIDWORKS. | zoo.dev/blog/announcing-zookeeper (2026-02-05) |
| Third-party SOLIDWORKS tools | LAD turns prompts into sketches, features and macros; users reported spatial mistakes. MecAgent sells automations, part generation and a standards checker ($0, $84 or $417 a month, or enterprise on-prem). SolidPilot is an open-source MCP server (AGPL-3.0, early alpha, "edit-fragile" reference resolver). hjbaard/SolidWorks-MCP has 54 typed tools that return measured volume, mass and box (MIT). Leo AI does part search and calculations; a Xometry test found its concept output was a 2D PNG. | LAD and MecAgent drive SOLIDWORKS through macros, which the constitution bans for this product. The MCP servers target SOLIDWORKS 2026 and are design references, not libraries to link. | news.ycombinator.com/item?id=46591100 (about 2026-01); mecagent.com/pricing-copilot (2026-09-28); github.com/eyfel/mcp-server-solidworks; github.com/hjbaard/SolidWorks-MCP; xometry.pro (2025-08-26) |
| DriveWorksXpress, design tables, Smart Components, library features | Rule-based variants of parts, assemblies and drawings. No LLM. DriveWorksXpress ships with every SOLIDWORKS licence. | The **non-LLM baseline**. The assistant's value must be measured against these, and against "the engineer plus ChatGPT with screenshots", not against nothing. | solidworks.com/partner-product/driveworksxpress |

**No shipped product designs a new part that mates to existing geometry with a verified fit**
(inferred from the sources above). Today, "working with an existing design" means one of:
- answering questions about the model;
- repairing the feature tree;
- performance edits;
- auto-constraining a dropped-in part;
- scripting a live session;
- editing a model that is defined in code.

#### Measured benchmarks (2026)

The skeptic re-read these figures. Only the figures that agreed across readings are quoted.

| Benchmark | What it measures | Figures |
|---|---|---|
| MUSE (arXiv 2605.28579, 2026-05-27) | CadQuery generation | Best model (GPT-5.5): 77.36% executable, 70.75% geometrically valid, 52.36% design intent (functionality 54.72%, manufacturability 48.58%, assemblability 53.77%). The open-source average for design intent is 5.20%. |
| CADEngBench (arXiv 2608.09296, 2026-08-10) | Engineering and manufacturability requirements, editing, assemblies (CadQuery) | 58.1% of executable outputs break at least one stated requirement. Editing supplied CAD succeeds 59.3-72.3% of the time. Editing is 4.64x easier than generating: 1,071 items pass only when editing, 231 only when generating. The exact joint (type plus entity) is right 23.3% of the time or less. End-to-end kinematics is right 15.8% or less. *The paper's B-rep validity and requirements-met ranges read differently in two fetches, so they are left out until someone reads the paper directly.* |
| RealCADBench (arXiv 2609.03773, 2026-09-03) | 12,632 tasks in 19 factory-automation categories (FreeCAD Python) | Executability 0.565-0.812. Solid IoU 0.28-0.54. Failures: missing fine structures, loss of part identity, wrong assembly placement. |
| BenchCAD (arXiv 2605.10865, 2026-05-11) | CadQuery generation and editing | Execution 67-94%, IoU about 0.19-0.28. Models replace sweeps and lofts with sketch and extrude. Code edits "silently corrupt unrelated features". |
| Text2CAD-Bench (arXiv 2605.18430, 2026-05-18) | Representation | Code beats command sequences: for one model, 13.3% invalid with CadQuery versus 67.3% with command sequences. 74% of GPT-5.2's hardest-level outputs were invalid. |
| P3D-Bench (arXiv 2606.11152, 2026-06-09) | Parts and assemblies | Assemblies are the hardest setting. |
| Parametric CAD Bench V3 (cadbench.ai, page dated 2026-09-24) | 100 FreeCAD tasks | Best allowed provider: GPT-6 Astra with Codex, 56.87 overall and the highest Create+Edit score (44.37), at $318 per 100 tasks. Gemini 3.8 Flash scored 36.19 overall and 31.10 on Image-to-CAD. The top entry overall (61.03) uses a provider the product excludes. |

**Caveats.**
- Every benchmark here measures agents that **write CadQuery or FreeCAD code**, which the
  constitution forbids in the product.
- None tests the product's configured models, gpt-5.6 and gemini-3.5-flash.
- So there is no measured evidence yet for a typed plan plus a deterministic executor. The owner's
  own evaluation has to create it.
- "OpenAI is stronger than Gemini at CAD" is a reasonable inference, not evidence for this
  product.
- The figures were read through a page-summarising fetch. Spot-check them before quoting them
  outside this repo.

**What works today and what fails** (inferred from the benchmarks above):

| Works | Fails |
|---|---|
| Single parts from primitives, sketch and extrude | Fine features, sweeps and lofts |
| Dimension-driven variants of a template | Feature orientation and side, for example a pocket that cuts into empty space |
| Editing existing parametric models | Placing several parts and mating them |
| Tree cleanup | Manufacturability |

No benchmark measures tolerance intent at all.

### 1.4 What carries over from smart_SW, and what is missing

**Roughly 55-65% of the codebase carries over. It is the reading, checking and plumbing half.**
Line counts were measured with `git ls-files`. The percentages are the reuse track's judgement.

| C# and pane (about 86k lines, about 62%) | Reuse | Python (about 81k lines, about 55%) | Reuse |
|---|---|---|---|
| Dump, IR, persistent references, ids, meshes, fasteners, geometry (19.7k) | 85% | `ir` (2.2k) | 90% |
| Capture, measure, interference (1.9k) | 90% | Mechanical checks (12.3k), as the critic | 65% |
| `Sw` gate (1.2k) | 100% | RMS checks (4.1k), grading generated parts | 60% |
| Guard (2.3k), kept, with a new allowlist added | 85% | Standards checks (6.3k) | 30% |
| Bridge (4.2k): envelope, secrets, versioning | 70% | Rules (1.7k) | 50% |
| `Rms` (10k): copy, scope, geometry reading, interop manifest, throwaway builder | 35% | Tools (7.8k) | 70% |
| Drawing probes (2.7k) | 15% | Agent loop and providers (7.6k) | 80% |
| Add-in Review (12.3k): backend, proxy, event pump, run folders, resolver | 55% | Report (5.5k) | 35% |
| Add-in Remodel (7k): the template for a concept host | 50% | Remodel (11.2k) | 40% |
| Tool service (3k) | 90% | Benchmark and replay (5.8k) | 55% |
| Terminal (5.8k) | 40% | Bridge client (1.1k) | 85% |
| Standards and Model check UI (1.9k) | 10% | Chat server (4.2k) | 65% |
| `web/shared` (2.8k) | 70% | MCP (0.6k) | 80% |
| Settings, native, add-in root (5.6k) | 85% | Drawings (1.5k) | 40% |
| Console host (5.4k) | 50% | Ingest (1.5k) | 10% |
| | | Geometry (0.45k) | 85% |
| | | CLI, pre-run and other root modules (7k) | 45% |

Weighted, that is about 59%. **Reuse does not mean the MVP is 60% done.** The creation core is
the hard part, and it is all new.

**What carries over, in words.**
- The evidence package (IR 1.6.0): transforms, mates, Hole Wizard data, fasteners, face planes and
  cylinders, meshes and captures.
- The design understanding code already derives: part roles, the joint map, fastener identity,
  the 1.5d engagement rule, tool envelopes, ISO 286 fits, and the drawing and package briefs.
- The bridge and the in-process tool service.
- SwGate and the pluggable guard pattern.
- The agent loop with OpenAI and Gemini, and the token-efficiency work (digests, pruning,
  caching, replay).
- The re-modeler's machinery: the refuse-overwrite copy, attestation, the interface-qualified
  allowlist, the target check before every write, the change log, the geometry gate, and "the
  model proposes, an executor applies".
- The pane infrastructure.

**Skeptic's correction: the checks are a critic for only half of each joint.** The joint map
builds hole instances only from Hole Wizard rows. A free cylinder face on a component that has
holes is never a member. A bought motor or gearbox model is usually an imported body with no Hole
Wizard data, and Principle IV forbids taking thread data from exported geometry. So on the
flagship part (an adapter plate), the checks report the bought side as gaps. The flange pattern
and thread must come from an owner catalogue and a new bounded face read. **The catalogue is a
prerequisite, not an option.**

**What is missing for creation.**

- **Sketch and feature generation.** Only the throwaway-part probe recipe exists, and its
  behaviour on 2024 SP5 is unverified.
- **A bounded face read of a chosen component.** The face dumper describes only the faces another
  dumper asked for. Bought components need their flange faces read.
- **A "use the current selection" read.** The add-in reads the selection only as a component.
- **Placing a part with mates.** AddComponent5, AddMate5 and GetCorrespondingEntity are never
  called. Which document owns a face's persistent reference inside a component is unverified
  (research R12).
- **Previews, undo and versions.** EditUndo2 is excluded on purpose, and the inverse of a create
  is a delete, which is denied. So versions should be rebuilt from the plan.
- **Images for the model.** Captures exist but never reach a provider.
- **Session caps.** There is no session token or money cap, and no per-concept iteration cap.
- **A `design` section in the standards profile:** stock thicknesses, minimum wall, bend radius,
  K-factor, preferred fasteners.
- **Closing the read-only guard's gaps** before any creation code exists.
  - Save3 and SaveAs3 are denied.
  - What passes by bare name: Save, Save2, SaveAs, SaveAs2, SaveAs4, SaveSilent, SaveAsSilent,
    IModelDocExtension.SaveAs and SaveAs2, and IPartDoc.SaveToFile*.
  - The real gaps: assembly components and mates (AddComponent5, AddComponents3, AddMate5,
    CreateMate, CreateMateData, InsertNewPart2, InsertNewVirtualPart), NewDocument,
    CreateCornerRectangle and CreateCenterRectangle, SetTransformAndSolve3, DefineAttribute, and
    temporary bodies (CreateBodyFromBox3, Display3).
  - No product code names any of these today.

### 1.5 The options, easiest to hardest

| # | Option | What it is | Writes a SOLIDWORKS file? | Effort | Seat sittings | Cost per session | Confidence |
|---|---|---|---|---|---|---|---|
| 1 | **Grounded ideation plus past-design retrieval** (Tier 1) | The engineer picks faces or components and states the goal ("mount a 400 W servo and a 10:1 gearbox to this plate, 30 kg at 200 mm"). The assistant returns an interface card, 2-4 approaches with trade-offs, sizing estimates from tested calculations, candidates from the owner's catalogue, and similar parts from recorded past designs. It creates no geometry. | No. It needs only a scope amendment. | 8-12 waves (2-4 weeks at this repo's pace); 6-9 engineer-weeks; plus 2-4 owner days for the catalogue and tasks | 1-2 | About $0.9-2.7 on gpt-5.6-terra, $1.6-4.8 on sol; more on the big assembly | Medium |
| 2 | **Template copy-and-drive** (Tier 2) | The owner authors 2-3 master parts (an adapter plate, an L-bracket) with global variables and Hole Wizard holes. Code copies one with 004's refuse-overwrite copy, derives each variable from the interface card and the catalogue, and drives it through 004's allowlisted equation keys. 004's geometry gate then checks the result. The engineer places the part: the product writes no assembly. | Yes, a copy in the run folder only. It extends exception 2 and needs no feature-creation member. | 4-8 engineer-weeks (about 5-10 waves, inferred from the engineer-weeks) | 1-2, beyond 004's own 3-4 | Not priced. Expected at or below option 3's range, since code derives the values (inferred). | Medium-low (it rides on 004's probes) |
| 3 | **Native concept parts plus placement** | A typed-operation C# executor builds native features (sketch, extrude, Hole Wizard, so thread data survives) into a new part in the run folder. It inserts the part into a new wrapper assembly that references the engineer's assembly and mates it to picked faces. It verifies with rebuild, mate status and interference. | Yes. It needs a sandbox-authoring amendment and a new allowlist guard. | 24-40 engineer-weeks. The native part and wrapper alone are 12-18 waves (track figure) and 12-20 engineer-weeks. Plan for 30-50% rework after the first seat contact. | 6-10, after 004's. That is 4-7 months of calendar at today's seat access, or 2-3 months with a development-seat licence. | About $2.6-4.5 on terra, $4.5-8 on sol, plus 5-20 minutes of seat time per concept | Low (the placement half) |
| 4 | **Variant explorer** (on top of 2 or 3) | Code sweeps template parameters offline (thickness, bent versus machined, bolt count, gearbox ratio) and scores clearance, mass, a cost proxy and calculation margins. The model reads a Pareto digest and explains it. Only the 2-3 chosen variants become configurations on the concept part. | Only on the concept part | +6-10 waves; +4-8 engineer-weeks once the owner's cost rates exist | 1-2 | About $4-7 on terra, $7-12 on sol (track figure, not re-checked) | Medium-low; blocked on cost data |
| 5 | **Full design partner** | Multi-part concept sub-assemblies, sheet metal, weldment frames, drawings through 012, motion clearance. | Several new write paths | 40-80+ waves; 6-12+ engineer-months, which is a floor | 12-25 | About $10-25 on terra, $20-50 on sol (track figure, not re-checked) | Low; research-grade |

**About the costs.**
- Prices are OpenAI's published per-1M-token prices, fetched 2026-09-28:

  | Tier | Input | Cached input | Output |
  |---|---|---|---|
  | gpt-5.6-terra | $2 | $0.20 | $12 |
  | gpt-5.6-sol (promotional) | $4 | $0.40 | $20 |

- Output tokens dominate the bill.
- Nobody knows which tier the plain `gpt-5.6` id maps to, and Gemini 3.5 Flash was not priced.
- A session grounded in the big assembly could cost several times these figures. The recorded
  review baseline is 12.4M input tokens, and the under-1M target is so far measured only by the
  replay.

**Dropped or deferred, with the reasons.**
- **An offline CadQuery or build123d builder** (5-8 engineer-weeks). Its output is a dumb STEP
  body the engineer must redraw. It adds a second kernel that must agree with SOLIDWORKS. It goes
  against the owner's native-first direction of 2026-09-19. ADR-001 allows OCP only for auxiliary
  check geometry, never as a host. None of these libraries is installed.
- **Temporary-body previews in the engineer's live document** (4-6 engineer-weeks plus 2-3
  sittings). The preview draws inside the engineer's document. The IModeler family is unguarded,
  and nobody knows whether Display3 marks the document dirty. An offline envelope check on the GLB
  meshes (trimesh and embree, both installed) gives most of the value with no seat.
- **FeatureWorks recognition.** Zero effort until the owner reopens STEP (decision 19A).
- **Free-form, general-purpose geometry from open prompts.** Research-grade: months to years,
  with uncertain quality.

### 1.6 The critical path: seat time, not code

- **No SOLIDWORKS write in this project has ever run on a licensed seat.** All of 004's blocking
  write probes (T033-T039) are still open.
- **Sittings get through less than planned.**
  - The 2026-09-26 sitting reached only its setup steps.
  - The next sitting is already planned at about 12 h 20 min over two days of 008-013
    validation.
  - 004's write probes are its last 25 minutes.
  - 004's own estimate to get stage 1 working is 4-6 waves plus 3-4 sittings.
- **Creation queues behind all of that** and adds its own probes: marks, modal dialogs, units,
  HoleWizard5 size strings, persistent-reference scope, Save3 on assemblies, and EPDM check-out.
- **The biggest lever is a licensed SOLIDWORKS seat on the development machine**, and no track
  priced it.
  - A term licence costs perhaps a few thousand dollars a year (inferred; check with the
    reseller).
  - It would turn the 3-6 month seat calendar into weeks.
  - Student and Makers licences do not permit commercial use (inferred).
  - ADR-001 already lists licensing an automation seat as an open question.
- **Owner data sets the start date as much as code does.** The roadmap's earlier asks are still
  open: a second real design with known defects, the drawing template, and the drawing-creation
  base repository. Writing 8-12 concept tasks with accepted answers and a catalogue of flange
  patterns and threads takes days of owner time.

### 1.7 Decisions and risks

**Decisions for the owner** (recommended option first):

| # | Decision | Options |
|---|---|---|
| 1 | The scope amendment for Tier 1 | **(A) One MINOR amendment: ideas and estimates are proposals, never findings or approval.** (B) No amendment, treating option cards as findings (not recommended). The current scope line says "the pilot produces review findings", and sizing numbers come close to "structural approval", which that line puts out of scope. |
| 2 | Where the chat lives | **(A) A mode of the Review tab, or a native chat page on the existing loopback chat server, which already runs sessionless multi-turn chat.** (B) A new purpose-named tab, which the owner must approve under the four-tab rule. (C) Un-hide the Ask terminal. Not recommended: it is hidden (`TaskPaneControl.cs:353`, `AskTabShown = false`), and the engineers are not command-line users. |
| 3 | Governance for any write | **(A) One "sandbox authoring" amendment, written once and shared by 012 drawing creation, template copy-and-drive, and Part 2's Simulation study on a copy.** (B) A separate exception per feature, which multiplies guard surfaces. |
| 4 | How creation touches the assembly | **(A) Tier 2 writes the concept part alone, and the engineer places it.** (B) A wrapper assembly that references the engineer's assembly, only if the probes pass. (C) A prefixed Pack and Go copy. |
| 5 | Vendor data | **(A) Only from the owner's catalogue; unknown stays unknown.** (B) The model may cite general knowledge, labelled unverified. |
| 6 | Images to the model | **(A) Numbers first (interface frames, bolt circles, clearances computed in code); images later, for orientation only.** (B) Images from the start, which touches the provider port, both adapters, pruning and replay pricing (2-3 engineer-weeks). |
| 7 | A development-seat licence | **(A) Price it now; buy it if any write work (Tier 2 or beyond) is wanted.** (B) Stay on the pilot seat's sittings. |
| 8 | The first part family, if creation goes ahead | **(A) Machined plates and brackets.** (B) Sheet metal. (C) Weldments. Sheet metal and weldments are each 6-10 engineer-weeks more, and 004's scope gate refuses both part types today. |

**Risks.**

- **Scope and the constitution.**
  - Creation is a third write path. The constitution allows exactly two, and a test asserts that
    no gate but the throwaway-part probe's may exempt the creation family.
  - 012 already needs a third write-path amendment, so concepts would make a fourth unless one
    sandbox-authoring rule covers both.
  - Editing sandbox copies of existing parts (for example adding mounting holes) is a separate,
    explicit decision. It is not a quiet widening.
- **Data egress.** Interface geometry, loads, meshes and later images would go to OpenAI or
  Gemini.
  - Gemini's unpaid-tier terms let Google use prompts and responses, with human review and no
    retention limit.
  - The OpenAI adapter leaves the Responses API's `store` at its default
    (`openai_provider.py:795-797`), so responses are probably stored server-side (inferred).
  - The rule has to come first: paid tiers only, a decision on `store` and retention, and only
    ids and numbers sent. No meshes, paths or profile values leave the machine; that is the
    `part_roles` pattern.
- **Export control.** The Standards check already looks for an export-control marking on
  drawings, so controlled technical data is a live concern. A document carrying that marking,
  detected locally, must never reach a provider. It should run code-only, or not at all.
- **Customer NDAs and vendor CAD terms.**
  - Customer part geometry in a machine is often under NDA.
  - Downloaded motor, gearbox and fastener models usually carry terms that restrict
    redistribution, and they may restrict sending the models to third parties.
  - Nobody has read what the owner's contracts allow. Each vendor's terms need reading.
- **Liability labelling.**
  - Every concept part carries a machine-readable "generated concept, not engineered" custom
    property.
  - The Standards tab refuses to release it, and the vault and the BOM never take it without
    review.
  - Guards, lifting points and other safety-related parts are excluded from concept
    generation.
  - Machine-safety responsibility stays with the builder: the ISO 12100 risk assessment, and in
    the EU the Machinery Regulation 2023/1230 from 2027-01-20.
  - The constitution already says a mutation is a proposal, never an engineering result
    (`constitution.md:182-184`). That extends to concepts and to sizing numbers.
- **Model fit.** The product's defaults (gpt-5.6, whose pricing tier is unlisted, and
  gemini-3.5-flash; `settings.py:103-105`) are not the benchmarked models. The benchmarks measure
  an architecture the product forbids. The first evaluation has to create the evidence.
- **LLM spatial weakness.** If the model chooses positions or sizes, the concepts will be subtly
  wrong, and that would also breach Principle II. Code must resolve every position, mate and
  dimension. The model chooses topology, part family and intent.
- **EPDM.** Production runs SOLIDWORKS 2024 with EPDM, and 004's EPDM probes (T139) are open.
  Open questions:
  - check-out prompts when a run-folder assembly rebuilds vaulted references;
  - how a concept part is promoted into the vault;
  - references that break when the engineer mates a run-folder part and the run folder is later
    cleaned.
- **Latency in the engineer's own session.** Building and re-dumping run on the engineer's
  SOLIDWORKS UI thread. The big assembly's dump "may take many minutes; do not click in
  SOLIDWORKS while it runs". Any verification loop that includes the engineer's assembly blocks
  the engineer's work and needs a partial dump.
- **The DriveWorksXpress baseline.** It ships with every licence and already makes rule-based
  variants. Tier 2 must beat it, and beat "the engineer plus ChatGPT with screenshots", on the
  owner's own tasks.
- **The shared in-memory document.** SOLIDWORKS keeps one in-memory document per file path. A
  wrapper assembly shares the engineer's open assembly, unsaved state included, and can rebuild
  it. Only attestation and never saving protect the engineer's files. The local help does not say
  whether Save3 without swSaveAsOptions_SaveReferenced (value 4) leaves dirty references unsaved.
  That is a blocking probe.
- **Token cost on long loops.** Tools must return digests from day one. The replay does not yet
  count image tokens.
- **Productizing.** If "general purpose" means selling it: AGPL-3.0 obligations (the project and
  PyMuPDF), the personal permission to reuse the Resilient Modeling rules, several SOLIDWORKS
  versions, and support. No track sized this.

### 1.8 Recommendation and evidence gates

**Two tiers. The read-only ideation comes first. Creation comes later, through the narrowest
write path the constitution nearly allows already.** Do not start from native feature creation
plus assembly mates.

**Step 0: decisions and data, almost no code, 1-2 weeks of calendar.**
- A 1-2 hour interview with the owner, plus a two-week log of where concept time goes and which
  part families recur. How does he ideate today: hand sketches, layout sketches, copying from a
  past machine, vendor configurators? What share of his custom parts are plates and brackets,
  sheet metal, or weldments?
- The data-egress rule (section 1.7) before any geometry leaves the machine.
- A decision on a development-seat licence.
- Keep the queued 008-013 and 004 sittings first. This work does not pre-empt them.

**Tier 1: grounded ideation plus past-design retrieval** (option 1).
- Where it runs: the chat server or a Review mode, so no new pane.
- Inputs:
  - an interface card built from Hole Wizard holes, mated faces, and a bounded face read of a
    picked component;
  - free space from the GLB meshes with embree;
  - an owner catalogue of 10-30 bought parts with flange patterns and threads;
  - a read-only search of recorded past packages ("similar interface, similar bracket").
    Machine builders mostly adapt earlier parts, and editing beats generating 4.64x.
- Output: option cards that cite IR entity ids, plus sizing estimates. Each estimate comes from a
  calculation tested against a published case and is labelled "Estimate, not approval".
- **Gate, on 8-12 real past concept tasks the owner writes:**
  - zero citations that fail to resolve;
  - zero numbers that do not trace to a tool result;
  - an owner rating of 3.5/5 or better, and he prefers it to his own "ChatGPT with screenshots" on
    at least 6 of 10 tasks;
  - at least 30 minutes saved per task;
  - unprompted use during two weeks of real work.

  **If it fails, stop.** Generating geometry will not rescue weak ideation.

**Tier 2: template copy-and-drive** (option 2).
- It starts only after both of these:
  - 004's blocking probes have verdicts, and stage 1 has run on a real part;
  - Tier 1 has passed its gate.
- Governance: one small amendment extending exception 2 to template copies, written so that 012
  can share it.
- **Gate, leave-one-out on at least 10 real joints** (remove a real part and ask for its
  replacement):
  - the hole pattern matches the real partner exactly;
  - the rebuild is clean;
  - the geometry gate passes;
  - attestation shows zero differences in the engineer's files;
  - the engineer accepts at least 60%, with no more than 5 minutes of edits each.

**Beyond Tier 2.** Fund the native executor and the concept assembly with mates (option 3) only
if Tier 2 shows that fixed template topology is what limits it. It should wait for a licensed
development seat and a probe of Save3 on assemblies. Sheet metal and weldments come after that, as
separate features, one family at a time.

---

## Part 2. The hand-calc assistant

### 2.1 The idea, as the owner asked it

> Add to the list, like a hand calc assistant where we can apply loads in our assembly and with
> all the context, an llm could help walk through the potential issues/solutions, not
> necessarily create CAD, but interpret the design enough to bounce ideas off of

### 2.2 The verdict

**Feasible and read-only. It is the best-grounded of the LLM-assistant ideas.** It can ship
before any concept creation, and later it becomes the checker for concept parts.

It follows smart_SW's own pattern:
- the engineer states or picks a load;
- code finds the load path and runs tested hand calculations;
- the model explains the results, ranks them, asks questions and suggests fixes;
- code re-checks each fix.

**The model never does the arithmetic.**

The critical path is owner data (the default-assumptions table, and past designs with known
failures) and the saturated seat queue. The rework risk is far lower than for a write feature.

### 2.3 The engineer's workflow

**Where it lives** (owner decision, recommended first):
- **(A) A "Loads" mode inside the Review tab.** It reuses the review's package, session,
  questions panel and labels, so no fifth tab is added.
- (B) A fifth purpose-named tab, "Estimate", which the owner must approve under the four-tab rule.
- (C) The command line and the report only, at first.

The hidden Ask terminal is not an option.

**Once per design, the engineer declares which world axis is up.** SOLIDWORKS stores no gravity
direction.

1. **Evidence.** The existing extract builds the package: joints, fasteners, holes, mates,
   contacts, masses, materials and meshes.
2. **Add a load**, in one of three ways.
   - **(a) Pick.**
     - The engineer selects a face, edge, vertex or component in SOLIDWORKS and presses "Use
       selection".
     - The add-in reads GetSelectedObject6 and turns it into a persistent reference. The capture
       command already does this for any selected entity (`SwReviewAddIn.cs:1432-1496`).
     - The reference resolves to an IR face or component. If the face was never dumped, a bounded
       read describes that one face or component and appends it to the package, the way a capture
       appends.
     - A small typed form takes the magnitude, the unit (a dropdown; code converts) and the
       direction: along the face normal, along a world axis, along an edge, or "gravity".
   - **(b) Words.**
     - For example "200 N down at the gripper", or "the gantry accelerates at 5 m/s² along +X".
     - The model maps the words to candidate entities and proposes a structured load: magnitude,
       unit, direction reference, and where it acts (a centre of mass, a face or a point).
     - The proposal shows as a card labelled **AI guidance** with Confirm and Edit.
     - Nothing enters a load case until the engineer confirms it. After that, it is the engineer's
       input.
   - **(c) Derived.**
     - The engineer picks a moving group of components or a sub-assembly.
     - Code sums the instance masses and finds the combined centre of mass from the transforms.
     - It applies m·g along the declared down direction. For a stated acceleration it also
       applies the inertial load −m·a at the centre of mass.
     - The mass check gates these loads. A part with no material, the 1000 kg/m³ default, an
       overridden mass, or a simplified bought model leaves the load unresolved or flagged until
       the engineer or the catalogue supplies the mass.
3. **Supports.** Code proposes the fixed components as ground and asks, through the questions
   flow, whether they really are the ground for this load case, or whether the machine is bolted
   down elsewhere.
4. **Load cases.**
   - The engineer names each one, for example "LC1 gravity + gripper 200 N" or "LC2 E-stop decel
     15 m/s²". Each holds loads, supports, factors (a dynamic factor, the owner's target safety
     factor) and combinations.
   - They are kept in `load-cases.json`: a versioned schema keyed by design id and configuration,
     in the run folder, never beside the source file.
   - The newest file for the same design id is carried forward, by the same rule that carries
     `exceptions.json` (`cli.py:1232`).
   - Every entity is referenced by id plus persistent reference, so it re-resolves after a new
     extract.
   - A per-component geometry fingerprint marks a load case "needs review" when a loaded or path
     component has moved or changed.
5. **Run.** Code traces the path from each load to ground and classifies each connection:
   - bolted, from the joint map with its fastener;
   - pinned;
   - contact bearing, from the contact list;
   - inside a weldment (rigid);
   - "mate only". A mate is not assumed to carry load, and the engineer is asked.

   It then decides whether each level is statically determinate.
   - Where the answer is determinate, it solves rigid-body statics and distributes bolt-group
     loads by the rigid-plate method.
   - Where a path is indeterminate (bolts plus dowels, several rails, redundant supports), it asks
     the engineer.
6. **Results.**
   - A table ranked by margin against the owner's target.
   - Each row is an estimate labelled "Checked by code" and "Estimate, not approval".
   - A row expands to the full calculation: inputs with units, the method and its citation, the
     assumptions, the excluded effects, and the source of every input (package, material
     database, owner table, or the engineer's answer).
7. **Walk-through and ideas.**
   - The model narrates the path, ranks the weak points and proposes fixes: another bolt, a dowel
     for shear, a thicker plate, a gusset, a different material or bolt class.
   - Each fix runs as a what-if in calculation space only, never in CAD, and is shown side by side
     with the original.
8. **Output.**
   - The report gains an "Estimates, not approval" section.
   - The engineer disposes of each estimate as with findings.
   - Phase 3 exports a load-case sheet for SOLIDWORKS Simulation.

### 2.4 Data: what the repo already has, and what is missing

**Already in the repo** (verified read-only at a8a8a09):

| Need | What exists | Where |
|---|---|---|
| Load path: connectivity from the load to ground | MateGraph: component adjacency from active mates, fixed roots, breadth-first depth. Mates record type, entities, alignment, distance and angle. The contact list gives size-for-size, zero-volume contacts, which are bearing surfaces. Mates are kinematic, so they are candidate connections only, never a proven load path. | `checks/rms/assembly.py:170-235`; `ir/models.py:543-576`; `checks/interference.py:334-375` |
| Joint map | Hole Wizard rows exploded into instances and paired by parallel, overlap and adjacency gates, plus screws, pins and clusters. Joint kinds: screw, pin, through bolt, unclassified. Recognised fasteners are placed, including non-Toolbox ones. **Gap:** only Hole Wizard holes are members, so bought motors and gearboxes show up as gaps. | `checks/joints.py`; `checks/joint_rules.yaml`; `checks/fastener_identity.py:330` |
| Fastener and hole data | Hole type, standard, size, thread, usable thread depth, hole depth, diameter, axis and faces. Fit and thread class. Drill, counterbore and countersink sizes. Fastener kind, thread, length, head, drive and axis. `parse_thread` gives nominal diameter and pitch. Per-instance axes give bolt-group centroids and radii. | `ir/models.py:578-720`; `checks/fastener.py:125-207` |
| Thread engagement | The owner's rule: at least 1.5d into steel and aluminium. Protrusion and usable thread are read off the geometry. It is a policy check; a stripping calculation would complement it, not replace it. | `checks/engagement_rules.yaml`; `checks/fastener.py:411-512, :752-883` |
| Mass and centre of mass | Mass, volume and centre of mass per document (CreateMassProperty2, system units), plus a row-major 4x4 transform per component in metres, so code can sum groups in the assembly frame. The mass checks flag no material, the 1000 kg/m³ default, and overrides. **Not in the IR:** moments of inertia. Only the re-modeler's gate reads principal moments. | `ir/models.py:301-386`; `Dump/PropertyDumper.cs:469-520`; `checks/mass.py` |
| Materials | The material name per part and its configuration. A class and density range only (`material_classes.yaml`). **Strengths and modulus are not in the IR**, and the extractor discards the database name. They can be read offline from the SOLIDWORKS material database, an XML file. This machine's 2024 install has 259 materials: 220 with a modulus, 219 with a tensile strength, 167 with a yield strength, and only 3 with an S-N curve. The DIN database has 207, all with yield. The seat may use a company database, so it needs a check. | `ir/models.py:317-351`; `PropertyDumper.cs:452-465`; `checks/material_classes.yaml`; the install's `sldmaterials` folder (parsed read-only 2026-09-28) |
| Section geometry | Cylinder and plane parameters, a bounding box and an area, in assembly space, but only for faces another dumper asked for. Clamped thickness is the Thickness property, else the bounding-box extent along the fastener axis (labelled derived), else unknown. Nothing identifies the face pair that sets a thickness. GLB meshes load in metres. trimesh 5.1.0 and embreex are installed. shapely, scipy and sectionproperties are not. | `ir/models.py:722-765`; `Dump/FaceDumper.cs:12-17`; `tools/checks_fastener.py:8-22`; `tools/measure.py`; `geometry/mesh.py` |
| Selection read for pick-to-load | The capture command reads the selection, whether face, edge or component, turns it into a scoped persistent reference and appends it to the package. The resolver reads the selection only as a component. No command returns the selection as an IR entity to use as a load point. | `SwReviewAddIn.cs:1432-1496`; `Review/SwEntityResolver.cs:265-275` |
| Part roles | Every document is labelled custom, bought or unclear, with a reason in words. No profile value is ever sent to the model. Bought parts are the ones whose ratings and masses must come from a catalogue. | `checks/part_roles.py` |
| Calculation record, units, labels, questions | `Calculation` holds model, inputs, assumptions, excluded effects, result, units and function version. `units.py` is the single pint registry, but it covers only lengths and angles. The 013 labels "Checked by code" and "AI guidance", and the answer-basis line. One question writer: at most 140 characters and 5 options, with text answers allowed. | `findings.py:78-88`; `units.py`; `report/review_words_v1.yaml`; `checks/questions.py:28-53`; `tools/session.py` |
| Agent plumbing and chat | One tool registry that validates, records and never raises, with per-run tool registration. Sessionless general chat. The loopback chat server with multi-turn sessions and a stop control. Replay and scorecard price and regression-test sessions offline. | `tools/registry.py`; `tools/context.py:124-170`; `chat/server.py`; `benchmark/replay.py` |
| Hand-off target: SOLIDWORKS Simulation | The installed interop (cosworks 32.5.0.48) has CreateNewStudy3, AddForce3 (21 parameters), AddGravity, AddRemoteLoad, AddRestraint, AddBoltConnector, AddPinConnector, AddBearingLoad, load cases and combinations, RunLoadCases, and free-body and connector force results. No product code references it, and no guard covers it. Whether the seat has a Simulation licence is unknown. | `SolidWorks.Interop.cosworks.dll` (reflected 2026-09-28); zero hits in `extractor/` |

**Missing:**

- **Load model.** A load model and load-case store: forces, moments, pressures, accelerations,
  directions, points of application, factors and combinations. `units.py` has no force, moment,
  stress, pressure, acceleration, torque, inertia or speed units.
- **Load path.** A structural load path. MateGraph is kinematic connectivity. Code must classify
  connections, decide determinacy and solve statics.
- **Sections and idealisations.** Section properties (A, I, Z, J, Q), and an idealisation of each
  member: cantilever, simply supported or fixed plate, column, L-bracket, weld group. The engineer
  confirms the idealisation, or it is labelled assumed.
- **Plate thickness from face pairs.** This is explicitly absent. It needs a bounded face read of
  the chosen component plus a finder for parallel, opposite planes.
- **Material strength and modulus.** Needs:
  - a read-only material-database parser;
  - an owner override table kept outside the public repo;
  - a seat check of which database the seat uses.

  Fatigue data is essentially absent, so an endurance limit is an estimate and labelled so.
- **Supports.** Support conditions: "fixed" is a modelling flag, not a structural support, and
  floor anchors are not modelled.
- **Up direction.** The up direction per design.
- **Inertia tensors** about the centre of mass per part. Needs an additive IR field (schema 1.7.0)
  from IMassProperty2, with a mesh-derived cross-check labelled derived.
- **Fastener data.** Fastener property class (8.8, 10.9, 12.9, A2-70), tightening method,
  tightening factor and friction. It comes from the owner's defaults table or a question; unknown
  stays unknown.
- **Welds.** Weld beads and sizes. They are not dumped; the engineer supplies the size.
- **Bought-part ratings.**
  - bearing C and C0;
  - linear guide and ball screw ratings;
  - motor torque, speed and rotor inertia;
  - gearbox ratio, efficiency, rated torque and inertia;
  - the real masses of simplified vendor models.

  This needs an owner catalogue with licence-clean data.
- **Motion data.** Motion profiles and duty cycles (Phase 2).
- **Stress concentrations.** Stress-concentration geometry at welds, shoulders and grooves. It is
  partial today: a simple fillet's radius and hole diameters.
- **Owner policy targets.** Required safety factors for static yield, fatigue and slip; dynamic
  factors; whether bolt threads sit in the shear plane by default.
- **Indeterminate joints.** Load-sharing rules for bolts plus dowels, several rails, and
  redundant supports. These must be engineer answers, never model guesses.
- **Selection command.** A "use the current selection as a load point" command that returns an IR
  entity.
- **Phase 3b only.** Whether the seat has a Simulation licence, and a guard for the cosworks
  interop.

### 2.5 The calculation library

Every calculation is tested against a published worked example before it is registered as a
tool. Tests may use the published inputs and answers as facts with citations. They must not copy
the text of Shigley, Roark's, Machinery's Handbook or VDI 2230. VDI 2230's examples need the
owner's purchased copy.

| # | Calculation | Method source | Phase | Validation case |
|---|---|---|---|---|
| 1 | Load resolution and rigid-body statics: gravity m·g and inertial −m·a at a group's centre of mass; 6-DOF equilibrium for determinate supports; a reaction check | Meriam and Kraige, *Engineering Mechanics: Statics*, ch. 3; Shigley 10th ed. ch. 3 | MVP | A simply supported beam's reactions and a 3D bracket problem from Meriam and Kraige ch. 3, to printed precision. Invariants: equilibrium residual below 1e-9 relative; the mass sum equals the assembly's read mass within 0.1%. |
| 2 | Section properties: rectangle, round, tube, rectangular tube, angle, channel; composites by the parallel-axis theorem | Roark's 8th ed. Table A.1; Shigley Table A-18 | MVP | Roark's closed forms plus a standard steel angle's tabulated properties. For example, a 20 x 40 mm rectangle gives I = 106,667 mm⁴. |
| 3 | Bolt-group distribution: direct plus eccentric (torsional) shear by the rigid-plate centroid method; tension from an overturning moment about a heel line | Shigley 10th ed. section 8-12 | MVP | Shigley's eccentric-load example: a 15 x 200 mm bar cantilevered to a 250 mm channel by four M16x2 bolts, F = 16 kN. The test reproduces the force per bolt, bolt shear, bearing and critical bar bending stress (Example 8-7 in the 9th ed.; confirm the numbering in the owner's edition). |
| 4 | Bolt shear, bearing on the bolt and the plate, net-section tension (shear plane in the thread or the shank) | Shigley 10th ed. section 8-12; Machinery's Handbook | MVP | Shigley's butt-splice example: two 1 x 4 in 1018 CD bars, 1/2 x 4 in splice plates, four 3/4-16 UNF grade 5 bolts. The safety factor for each failure mode (Example 8-6 in the 9th ed.). |
| 5 | Bolt tension with preload: kb, km (frustum), joint constant C, preload Fi (0.75 Fp reusable, 0.9 Fp permanent), torque T = K·Fi·d, load, yield and separation factors | Shigley 10th ed. sections 8-7 to 8-9; VDI 2230-1:2015 as the full-model reference later; ISO 898-1 proof stresses | MVP | Shigley's pressure-vessel example (36 kip separating force; Example 8-5 in the 9th ed.) and its member-stiffness example. Computed check: M10 8.8 with Sp 580 MPa and At 58 mm² gives Fi = 25.2 kN and T about 50.5 N·m at K = 0.2. |
| 6 | Joint slip (friction grip): minimum clamp load for a transverse load, per interface and bolt count, with preload loss and tightening scatter | VDI 2230-1:2015 requirement R8; Bickford, *An Introduction to the Design and Behavior of Bolted Joints* | MVP | A worked R8 example from the owner's copy (numbers cited, text not copied), cross-checked against a Bickford hand case. Boundaries: μ = 0 or zero preload gives unresolved, never infinite capacity. |
| 7 | Thread stripping, internal and external: required engagement length and stripping load; complements the 1.5d rule | Machinery's Handbook, length of engagement (FED-STD-H28 shear areas); VDI 2230-1:2015 section 5.5.5 | MVP | The Handbook's worked example in the owner's edition plus FED-STD-H28/2B shear areas. Ordering test: for matched steel strengths at 1.5d, stripping capacity exceeds bolt tensile capacity. |
| 8 | Dowel and pin shear, single and double, and pin bearing on the plate | Shigley 10th ed. ch. 7; ASME B18.8.2 and ISO 8734; Machinery's Handbook dowel tables | MVP | A closed-form clevis-pin double-shear case, plus the Handbook's tabulated loads for hardened dowels. The table is adopted only if it states that it is formula-based; otherwise it is a cross-check with its rounding stated. |
| 9 | Cantilever bracket bending and deflection: end load, uniform load, end moment; later an L-bracket as two members | Roark's 8th ed. Table 8.1 (cases 1a, 2a, 3a); Shigley Table A-9 | MVP | Exact: steel bar b = 20 mm, h = 40 mm, L = 300 mm, P = 2 kN, E = 200 GPa gives tip deflection 0.8438 mm and root stress 112.5 MPa. Plus a Shigley ch. 4 superposition example. |
| 10 | Plate bending: rectangular and circular plates, simply supported and fixed edges, uniform and central loads, interpolating the tabulated a/b ratios | Roark's 8th ed. Table 11.4 (e.g. case 1a) and Table 11.2 (e.g. case 10a); Timoshenko and Woinowsky-Krieger | MVP | Roark case 1a at a/b = 1 (α 0.0444, β 0.2874), cross-checked with Timoshenko: a 300 mm square, 10 mm steel, 100 kPa gives σ 25.9 MPa and y 0.180 mm. Circular case 10a (a = 100 mm, t = 5 mm, q = 0.1 MPa, ν = 0.3, E = 200 GPa) gives y 0.278 mm and σ 49.5 MPa. Plus interpolation tests. |
| 11 | Fillet-weld throat stress by the line-weld method: direct shear, torsion and bending of weld groups; throat 0.707 h | Shigley 10th ed. ch. 9, Tables 9-1 and 9-2; Blodgett, *Design of Weldments*; AWS D1.1 allowables only if the owner adopts them | MVP | Shigley's first weld example (50 kN into a 200 mm channel, Example 9-1). Computed check: two 100 mm welds, h = 6 mm, 20 kN direct shear gives τ 23.6 MPa. |
| 12 | Column buckling: Euler, and the Johnson parabola below the transition slenderness; end-condition constants; design factor | Shigley 10th ed. sections 4-11 to 4-13; Roark's ch. 15 | MVP | Shigley's pinned round column: 22 kN, l = 1.5 m, design factor 4, Sy = 500 MPa, E = 207 GPa gives d about 37.5 mm with l/k about 160, above the transition of 90.4, so Euler governs. Computed; confirm against the edition. |
| 13 | Stress concentration factors, first subset: finite plate with a central hole in tension, shaft shoulder fillet in bending and torsion, grooved shaft | Pilkey and Pilkey, *Peterson's Stress Concentration Factors*, 3rd ed.; Shigley Table A-15 | MVP | A plate with a hole at d/W = 0.25 gives Kt (net section) 2.42, matching the chart. As d/W goes to 0 it gives 3.0. The chart values are cited by figure number. |
| 14 | Static safety factor against yield: von Mises for ductile materials, maximum shear as an option, maximum normal for brittle ones; margin against the owner's target | Shigley 10th ed. ch. 5 | MVP | Shigley's first static-failure example: Sy = 100 kpsi under several stress states, by distortion energy and maximum shear (Example 5-1). |
| 15 | Motor torque and inertia sizing with a gearbox: reflected inertia J/i², peak and RMS torque over a duty cycle, inertia ratio, efficiency; belt, ball screw, rack and conveyor kinematics | Oriental Motor technical reference; SEW-EURODRIVE, *Drive Engineering: Project Planning of Drives* | Phase 2 | A printed SEW travel-drive or hoist example and an Oriental Motor ball-screw example. Computed check: 50 kg, 5 m/s², μ 0.1, pulley r = 25 mm, i = 5, η 0.9, rotor 1e-4 kg·m² gives 1.661 N·m at the motor, 1.761 N·m peak and an inertia ratio of 12.5:1. |
| 16 | Rolling bearing L10 life: (C/P)^p with p = 3 for balls and 10/3 for rollers; P = X·Fr + Y·Fa; cubic mean load over a duty cycle | ISO 281:2007; Shigley 10th ed. ch. 11; makers' catalogues | Phase 2 | Shigley's first bearing example: 5000 h at 1725 rev/min and 2 kN at 90% reliability needs C10 about 16.1 kN (computed 16.06 kN; Example 11-1). Plus a catalogue example. |
| 17 | Shaft torsion, bending and combined loading (DE-Goodman), angle of twist | Shigley 10th ed. ch. 7 (section 7-4) and ch. 3 | Phase 2 | Exact: T = 100 N·m, d = 20 mm gives τ 63.66 MPa. Shigley's shoulder example, fatigue safety factor by each criterion (Example 7-1). |
| 18 | Keys: shear and crushing of parallel keys; key length for torque | Shigley 10th ed. section 7-7; DIN 6885 and ISO 773 | Phase 2 | Shigley's key-selection example: a 1-7/16 in shaft, 40 hp at 600 rev/min (Example 7-6). |
| 19 | Fatigue safety factor: Marin-modified endurance limit, Kf from Kt and notch sensitivity, Goodman (Gerber, ASME-elliptic, Soderberg as options), first-cycle yield | Shigley 10th ed. ch. 6 | Phase 2 | Shigley's Marin example (Example 6-8) and the 1.5 in AISI 1050 CD bar under 0 to 16 kip with Kf = 1.85 (Example 6-10). |
| 20 | Bolt fatigue: alternating and mean bolt stress from the joint constant; the Goodman line with rolled-thread endurance strengths | Shigley 10th ed. section 8-11; VDI 2230-1 requirement R10 | Phase 2 | The Shigley section 8-11 example in the owner's edition, plus a VDI R10 cross-check. |
| 21 | Linear guide and ball screw life: (C/P)³ times the rated distance or revolutions, with load and speed factors | ISO 14728-1; vendor catalogues | Phase 2 | A worked example from a vendor catalogue the owner uses, to printed precision. |
| 22 | Hand-off consistency: hand-calc reactions and stresses against a Simulation study's free-body and connector forces | This library; SOLIDWORKS Simulation results | Phase 3 | A shipped Simulation verification problem or a NAFEMS benchmark whose closed form matches a library calculation, within the owner's tolerance. |

The MVP has 14 calculations. *The research's summary says Phase 2 adds nine more, but its table
lists seven Phase 2 rows (15-21) and one Phase 3 row. The difference is probably the
motion-profile and duty-cycle RMS work in the Phase 2 list (section 2.9). Reconcile the count when
specifying.*

Every calculation also carries Principle III's tests for invalid input, missing input, unit
mismatch and boundaries. On incomplete input it returns unresolved.

### 2.6 The model's role: it orchestrates, it never calculates

This is Principle II. SINTEF puts it as "let AI orchestrate, not calculate".

1. **Understand the design.** The model reads the package brief, the part roles, the joint-map
   digest and the path code built. It names the path in words, for example: "the 200 N at the
   gripper goes through the gripper plate, 4 x M5 into the carriage, then two bought guide blocks,
   the rails and the frame".
2. **Choose calculations.**
   - It picks tools by id and never passes numbers of its own: `estimate_joint`,
     `estimate_member`, `derive_gravity_load`, `derive_inertial_load`, and `what_if`.
   - The only numbers it may pass are ones it transcribed from the engineer's words. Those arrive
     as a proposed load the engineer confirms before use.
   - Code does all unit conversion.
3. **State assumptions.** Every idealisation appears on the estimate as a line of assumptions:
   support type, rigid plate, member model, threads in the shear plane, preload source. An
   idealisation the engineer has not confirmed is marked "assumed".
4. **Ask when it cannot know.** It uses the 013/009 questions flow: one decision per question, at
   most 140 characters, up to 5 options.
   - **Code asks the deterministic questions:** bolt class unknown, an indeterminate joint, a mass
     taken from a default.
   - **The model asks the judgement questions:** which load case governs, the operating
     scenario.
   - Example: "Joint J-7 has 4 bolts and 2 fitted dowels. Who carries the shear?" The options are
     "Dowels only", "Bolts by friction", "Shared by stiffness" and "Not sure".
   - An indeterminate path is never resolved silently. "Not sure" runs both bounding assumptions
     and shows the worse result.
5. **Walk through and rank.**
   - Code computes the ranking: margin divided by the owner's target, lowest first.
   - The model explains why each weak point is weak and which failure mode applies: slip,
     separation, stripping, bearing, yield, buckling or deflection.
6. **Suggest fixes.**
   - Each proposed fix runs as a `what_if` variant, and its result is "Checked by code".
   - A suggestion outside the library, such as a redesign idea, stays "AI guidance" and says it is
     unchecked.
7. **Labels, reusing 013.**
   - Every calculation and the code-built path read "Checked by code", plus a fixed "Estimate, not
     approval" badge.
   - The model's narrative, ranking explanation and suggestions read "AI guidance", with the
     answer-basis line.
   - A load parsed from words stays "AI guidance" until the engineer confirms it.
8. **What it does not do.**
   - It does not approve anything, and it does not turn a result into pass or fail.
   - It does not invent a strength, a friction value or a rating.
   - It does not write CAD.
   - It does not estimate outside the library. Complex castings, dynamics beyond Phase 2, and
     thin-sheet stability are named as out of scope and routed to Simulation.

**Record shape** (owner decision, recommended first):
- **(A) Reuse Finding plus Calculation with check ids `estimate.*`.** The report, the pane cards,
  dispositions and labels then work unchanged.
- (B) A new record type.

**Status rules:**

| Outcome | Status |
|---|---|
| A shortfall. It depends on the idealisation, so it is never "demonstrated". | suspected |
| Meets the target | checked-within-scope |
| A missing input | unresolved |

### 2.7 Constitution and scope

- **Amendment 1.1.0 to 1.2.0 (MINOR).** Rewrite the scope line (`constitution.md:192-194`) to
  read:

  > The pilot produces review findings and engineering estimates. An engineering estimate is a
  > hand calculation of the design under loads the engineer states, computed by the tested
  > calculation library and labelled Estimate, not approval. Autonomous GD&T creation, general
  > drawing dimensioning and structural approval (certifying a design safe, sign-off, compliance
  > with a code or a machine-safety standard) remain out of scope.

  Record it in the Sync Impact Report. Existing specs need no migration.
- **A new Technical Constraints subsection, "Engineering estimates".**
  - (a) Every calculation cites its published method (book, edition, section or table). It has a
    test that reproduces a published worked example to its printed precision, plus Principle
    III's tests for invalid input, missing input, unit mismatch and boundaries. A calculation
    without its validation test is not registered.
  - (b) Every estimate states its idealisation. Each idealisation is either confirmed by the
    engineer or labelled assumed.
  - (c) The model never resolves a statically indeterminate path; code asks the engineer.
  - (d) No default strength, friction, preload or rating clears an estimate unless the owner's
    table declares it. Every result that used such a default cites it.
- **Status words.**
  - Use the status rules of section 2.6. Never "pass", "approved" or "safe".
  - Every estimate record, pane view and report section carries "Estimate, not approval" and a
    source label.
  - The Principle VI analogue is written once: "Estimating the stated load cases does not
    establish adequacy for loads not stated."
- **No write path.**
  - The read-only rule (`constitution.md:141-145`) is unchanged.
  - The selection read, the bounded face read and the material-database parse are reads. The
    read-only guard's denylist grows if any of them touches a writing family.
  - Creating a Simulation study writes into the model file, so Phase 3b needs a separate
    exception (a copy, or the shared sandbox-authoring amendment of section 1.7) and a cosworks
    allowlist guard.
- **Principle II shapes everything.** Code does:
  - load resolution;
  - bolt-group distribution;
  - section properties;
  - every formula;
  - the what-if variants;
  - all unit conversion.

  `units.py` stays the only converter, extended to force, moment, stress, pressure, acceleration,
  torque, inertia and speed.
- **Principle III is the dominant cost, and it must be budgeted as such.**
  - Tests before code for each calculation.
  - Golden worked examples.
  - An end-to-end golden estimate set on the recorded big and small assemblies (replay, no
    key).
  - The owner's past-design gate, with the answer key withheld from the agent.
- **Principle I.**
  - A missing input stays unknown.
  - A bounding-box thickness, a mesh-derived section or inertia, and a default mass are labelled
    derived and cap the estimate's status.
  - The mass checks' findings gate gravity loads.
- **Principle IV.**
  - Thread, fastener and hole data come from native Hole Wizard data and fastener identity, never
    from meshes.
  - Section dimensions come preferably from native face planes; meshes are supplementary.
- **Data egress.** The same rule as section 1.7, plus one addition: a document carrying the
  export-control marking runs code-only estimates, with no provider call.
- **Liability.**
  - The product never states that a machine or part is safe.
  - Guards, lifting points, safety functions and anything under an ISO 12100 risk assessment are
    flagged "requires qualified approval".
  - For EU delivery, the Machinery Regulation (EU) 2023/1230 applies from 2027-01-20, and
    responsibility stays with the builder.

### 2.8 State of the art

| Tool | What it is | Why it does not cover this idea | Source (date) |
|---|---|---|---|
| MITCalc | An Excel library of mechanical calculations. Its bolt module cites ANSI, ISO, EN, DIN and VDI 2230. It makes no claim of independent validation. Practitioners note it blends standards; for example, it has no direct tightening-factor input. | No design context from the assembly | mitcalc.com (2026-09-28); industrialmonitordirect.com (2026) |
| MDESIGN bolt, SR1, MechanixCalc | Dedicated VDI 2230 and Eurocode 3 bolt calculators. MDESIGN advertises CAD integration and verification documents. | Reference implementations to cross-check the bolt calculations against | mdesign.de; hexagon.de; mechanixcalc.com (2026-09-28) |
| eFatigue | Web fatigue calculators with material data and stress-concentration factors | No assembly context | efatigue.com (2026-09-28) |
| SOLIDWORKS SimulationXpress | Ships with SOLIDWORKS. A single solid body; fixed fixtures only; forces and pressures only; static and uniform loads. | Too narrow for joint loads in an assembly | blogs.solidworks.com; solidsolutions.co.uk (2026-09-28) |
| SOLIDWORKS Simulation (Professional, Premium) and its API | The full study workflow, with bolt, pin and bearing connectors and load-case combinations. Validated by 52 NAFEMS benchmarks and shipped verification problems. | The study lives in the model file, so automating it is a write. The seat's licence is unknown. | cati.com; help.solidworks.com 2024 API (2026-09-28) |
| SOLIDWORKS LEO and AURA | LEO sets up linear static studies, predicts results with surrogate models and reports factor of safety. | Needs 2026 SP1 or later connected to 3DEXPERIENCE. Not on the 2024 SP5 seat. | hawkridgesys.com (2026-02-23, updated 2026-09-02) |
| Mathcad Prime, SMath Studio, Excel sheets | Calculation sheets with native units, validated by checker sign-off. Mathcad Prime 12 ships no native AI; a community MCP server exists. | None reads a CAD assembly | ptc.com; smath.com (2026-09-28) |
| Calcs.com (formerly ClearCalcs) | Calculators aligned to structural codes, each with dozens of test cases, automated regression and outside professional-engineer verification. Calcs AI (beta) calls verified calculators rather than inventing math. | **The closest commercial analogue to this design**, but it covers buildings, not machines, and has no CAD context | calcs.com (2025-09-09, 2026-09-22) |
| SkyCiv | Structural analysis with an AI assistant that flags ambiguous prompts. Public "AI skills" teach agents to call 150+ calculators through the API instead of computing. | Civil and structural work | skyciv.com; github.com/skyciv/skyciv-ai-skills (2026-09-28) |
| CalcTree AI | AI that builds and extends calculations, including Python analysis | The model writes code, which the constitution forbids | calctree.com (2026-03-24) |
| GeoMCP (SINTEF) | Method cards (equations, variables, units, citations), a deterministic engine with dimensional checks, MCP tools, validated against the official Eurocode 7 worked examples | **The same "published worked example per calculation" pattern**, applied to geotechnics | blog.sintef.com (2026-03-12) |
| DUCTILE (research) | Agentic orchestration of structural analysis at an aerospace manufacturer. The LLM adapts the path; verified tools execute. | Found that engineers can end up in an exhausting supervisory role | arXiv 2603.10249 (2026-03-10) |
| LLM accuracy benchmarks | SoM-1K: the best of 8 models solved 56.6% of 1,065 strength-of-materials problems. TPS-CalcBench: 13 models scored 12.6-87.9. A hybrid structural pipeline went from 41.5% to 83.3% with verification and solver delegation, and names unit, equilibrium and load-combination errors. | All support tool-only arithmetic | arXiv 2509.21079 (rev. 2026-08-01); arXiv 2604.17966 (2026-04-20); PMC13287573 (2026-04) |

**Where this assistant fits.** Every tool above does one of two things:
- it calculates without design context (MITCalc, eFatigue, Mathcad, Calcs.com);
- or it has design context but no hand-calc reasoning on this seat (Simulation; LEO needs 2026
  connected).

None reads an assembly's joint map, fasteners, threads, masses and materials to find the load path
and pick the calculations. That design context, plus validated calculations and honest labels, is
the gap.

### 2.9 Phases and estimates

| Phase | Scope | Waves | Seat sittings | Engineer-weeks | Confidence |
|---|---|---|---|---|---|
| **0: decisions, amendment, data** | The owner decides: where it lives, the record shape, the status rules, the default-assumptions table (bolt class, friction, tightening factor, target safety factors, dynamic factors), the material source, and the egress rule. Draft amendment 1.2.0 and a spec skeleton. The owner gathers 6-10 past designs, at least 3 with known field failures or redesigns. A 15-minute seat check rides on the next queued sitting: which material database the seat uses, and whether Simulation is licensed. | 0.5-1, plus 2-4 owner days | 0 of its own | 1-2, plus owner days | High |
| **1: MVP**, static estimates on bolted, pinned and bracketed joints (gravity and stated loads) | Waves per item: load model, units, load-case store with carry-forward and staleness (2-3); selection-read bridge command and bounded face read (1-2); material-database parser, override table, IR database-name field, fastener class (1-2); idealised sections and a face-pair thickness finder (1-2); load-path graph, determinacy, 6-DOF statics, rigid-plate bolt groups, indeterminacy questions (3-4); the 14 calculations with their validation tests (5-7); model layer: tools, prompt, what-if, records, labels, questions (2-3); pane load-case panel, confirm cards, ranked results, report section (2-3); golden estimates, replay pricing, gate harness (1-2) | 18-26 (about 4-7 calendar weeks of offline code) | 2-3: a 30-45 minute probe of the selection read, the face read and the database name; a 2-hour owner session on 2-3 real designs; a fix-up re-run if needed. All queue behind 008-013 and 004. | 18-28 (library 6-9, load path and statics 3-4, UI and report 2-3, model layer 2-3, the rest 5-9) | Medium. Read-only, so much lower rework risk than 004's write path. |
| **2: dynamics, fatigue, bearings, drives** | Inertia-tensor read (schema 1.7.0) plus a mesh cross-check (1-2); motion profiles, inertial load cases, RMS over a duty cycle (2-3); drive sizing with an owner catalogue schema (3-4); bearing L10 (1-2); shafts and keys (1-2); fatigue and bolt fatigue (2-3); duty-cycle entry and a drive-sizing view (2-3); evaluation (1) | 13-20, plus 3-5 owner days for a licence-clean catalogue | 1-2: an inertia-read probe and a duty-cycle session on a real axis | 15-24 | Medium-low. Fatigue inputs are mostly estimated, and the catalogue is owner time. |
| **3a: read-only hand-off to Simulation** | A load-case sheet per load case: each load's magnitude and direction in the assembly frame, the target face with its persistent reference and a capture, fixtures, bolt and pin connectors with Phase 1 preloads, and the hand-calc reactions and stresses to compare. The engineer builds the study by hand, and a comparison check reads the results the engineer enters. | 3-5 | 0-1 | 2-4 | Medium. No amendment. |
| **3b: automated study on a copy** | A copy (Pack and Go into the run folder; behaviour unverified); a Simulation executor (create study, forces, gravity, restraints, connectors, load cases, mesh, run, read results); hand calculation and FEA side by side. Needs a Simulation licence on the seat, a write amendment, a cosworks allowlist guard with generated tables and reflection tests, attestation of the engineer's files, and 004's probes first. | 12-20 | 4-8, after 004's write probes: 3-6 months calendar at current seat access, or weeks with a licensed development seat | 10-18 | Low |

**Totals.**

| Scope | Waves | Engineer-weeks |
|---|---|---|
| MVP alone | 18-26 | 18-28 |
| MVP plus Phase 2 | 31-46 | 33-52 |
| Everything, including 3b | 49-76 | 45-78 |

The biggest schedule lever is again a licensed SOLIDWORKS seat on the development machine.

### 2.10 Risks

- **False confidence.** A tidy table of safety factors reads as approval. Mitigations:
  - an "Estimate, not approval" badge that cannot be dismissed;
  - no pass status, ever;
  - idealisation lines on every row;
  - the evidence gate before anyone relies on it;
  - structural approval kept explicitly out of scope.
- **Idealisation errors.** Once the arithmetic is in code, this is the dominant error class.
  - The evidence: Tool-Induced Myopia (arXiv 2511.10899, v2 2026-04-20) found that tools raised
    final-answer accuracy by up to 19.3 points, but the errors moved to assumptions and logic.
  - The error types: treating a mate as a load path, wrong supports, ignoring stiffness sharing, a
    bracket that is not a cantilever.
  - Mitigations: code classifies connections and detects indeterminacy; the engineer confirms
    idealisations; "Not sure" runs both bounds; a Phase 3 Simulation cross-check; known failures
    in the gate.
- **Units.** The IR is in metres and radians, drawings are in mm or inches, and the engineer may
  say "lb" or "kgf".
  - Mitigations: one pint registry, unit-mismatch tests per calculation, and the model never
    converts.
  - A 2026 study found that LLM-only structural pipelines mishandle units and load combinations
    and violate equilibrium.
- **Wrong masses.** Parts with no material, overridden masses, and simplified or empty vendor
  models give wrong gravity and inertial loads. The existing mass checks gate derived loads, and
  bought parts take catalogue masses.
- **Missing material and fastener data.**
  - The seat's material database may differ from this machine's.
  - The fastener class is unknown.
  - S-N data is essentially absent.

  Unknown stays unresolved, the owner's defaults table is cited in every result it feeds, and
  fatigue is labelled low confidence.
- **Liability and machine safety.** The builder keeps responsibility (ISO 12100; EU 2023/1230
  from 2027-01-20). Guards, lifting points and safety functions are flagged for qualified
  approval. The product never says safe.
- **Data egress and export control.** As in section 1.7: paid tiers, a store and retention
  decision, only ids and numbers sent, and code-only mode for marked documents.
- **Textbook licensing in a public repository.** Cite the inputs and answers as facts. Never copy
  the books' text.
- **Model fit.** gpt-5.6 and gemini-3.5-flash are untested at narrating load paths. SoM-1K rules
  out raw model arithmetic. Only the owner's evaluation says whether the orchestration is good
  enough.
- **Supervisory burden.** DUCTILE's warning applies. Checking a result must be faster than doing
  it:
  - inputs visible;
  - one click to the calculation;
  - the first questions batched.
- **Scope creep into FEA.** Complex castings, thin-wall stability and contact-dominated joints
  are outside hand calculations. The library says so and routes them to Simulation, rather than
  stretching an idealisation.
- **The seat queue and licence unknowns.** The selection, face, database-name and inertia reads
  need seat probes behind 008-013 and 004. Phase 3b needs a Simulation licence that may not
  exist.
- **Token cost on the big assembly.** Use the package brief, digests and pruning, and price with
  the replay before any pane default changes.

### 2.11 The evidence gate

Nothing ships to real use until all four gates pass. Phase 2 starts only after them.

1. **Library gate.**
   - 100% of registered calculations pass their published worked-example tests, plus a second
     independent source where one exists.
   - Every calculation has tests for invalid input, missing input, unit mismatch and boundaries,
     and asserts unresolved on incomplete input.
2. **Replay gate**, on the recorded big and small assemblies, with no key:
   - zero numbers in any answer that do not trace to a tool result;
   - zero entity ids that fail to resolve;
   - every estimate carries its idealisation and its source labels;
   - the token cost is priced.
3. **Owner past-design gate**, with the answer key withheld from the agent. Use 6-10 past designs:
   - at least 3 known field failures or redesigns, for example a bracket that cracked or
     deflected, bolts that slipped or loosened, a stripped thread, or an undersized motor or
     gearbox;
   - at least 3 known-good designs that have run for years.

   To pass:
   - each known failure appears in the top 3 weak points with the right failure mode. If the tool
     says it cannot model the case, that counts as a miss;
   - no known-good design gets a shortfall at the owner's accepted margin (at most 1 false alarm
     per design);
   - where original hand calculations or a Simulation study exist, stresses and deflections agree
     within a tolerance the owner sets (proposed 15% and 20%) on at least 3 cases where the
     idealisation applies.
4. **Usefulness gate:**
   - the owner rates the walk-throughs 3.5/5 or better;
   - at least 30 minutes saved per case against his own hand calculation or spreadsheet;
   - its questions are judged sensible;
   - it is used unprompted during two weeks of real work.

**If it misses known failures, stop.** Fix the idealisations and load-path rules before adding any
Phase 2 calculation.

---

## Part 3. How the two relate

### 3.1 Shared foundations: build each once

| Foundation | Concept assistant (Part 1) | Hand-calc assistant (Part 2) | Build once as |
|---|---|---|---|
| **The interface card and bounded face read** | The bought side of a joint (flange faces, bolt circle), and the faces the engineer picks | Plate thickness from face pairs, and a load's point of application | One "use the current selection" bridge command, one bounded face read of one component, and one face-pair and bolt-circle finder. Both appear in Phase 1 of either plan, so whichever starts first builds them. |
| **The owner catalogue of bought parts** | Flange patterns, threads, envelopes | Ratings, real masses, rotor and gearbox inertia, efficiencies | One schema and one loader, kept outside the public repo like the standards profile. Licence-clean data only; unknown stays unknown. |
| **Labelling** | "Proposal", never a finding or approval; "AI guidance" for option cards | "Checked by code", "AI guidance" and the fixed "Estimate, not approval" badge | The 013 labels and one words file (`review_words_v1.yaml`), extended once |
| **The calculation library** | Option cards need sizing numbers (bolts, plates, motors, bearings). The skeptic ruled that these must be tested against published cases and labelled as estimates. | This *is* the library | Part 2's library. Tier 1 ideation calls it rather than growing its own `calc_*` tools, which removes the validation work from Tier 1's budget. |
| **Units** | Interface frames, clearances, torques | Forces, stresses, pressures, accelerations, inertia | One `units.py` extension |
| **The chat surface** | Option cards and follow-ups | Walk-throughs, confirm cards, what-ifs | One surface: a Review mode or the existing loopback chat server. Not the hidden Ask terminal, and no fifth tab without the owner's approval. |
| **Evaluation on past designs** | 8-12 concept tasks with accepted answers | 6-10 designs, at least 3 with known failures | One local corpus of the owner's past designs, kept outside the public repo, with answer keys withheld from the agent. One replay and scorecard harness. The same designs can serve both, since each failure case is also a "what would you have done instead" concept task. |
| **Data egress rule** | Interface geometry, and later images | Loads, geometry-derived numbers, material names | One rule: paid tiers, a `store` and retention decision, ids and numbers only, and code-only mode for export-marked documents |
| **Scope amendment** | "Ideas and concept proposals" | "Engineering estimates" | **One MINOR amendment (1.2.0) that covers both**, rather than two in a row |
| **Sandbox-authoring amendment** | Template copy-and-drive; later, native concept parts | Phase 3b, the Simulation study on a copy | One write-path amendment, shared with 012 drawing creation |

A rough, inferred figure for the saving: building both read-only MVPs together costs perhaps 23-34
waves rather than 26-38. The face read, the catalogue loader, the units extension, the chat
surface and the evaluation harness are built once, and Tier 1's sizing calculations come from Part
2's library.

### 3.2 A suggested order

Both read-only pieces need no write path. So the hand-calc MVP could come first, or run alongside
grounded ideation.

0. **Keep the queue.** Run the 008-013 validation sitting and 004's write probes first. Neither
   idea pre-empts them.
1. **Step 0 for both at once.** It takes about 1-2 weeks of calendar, mostly owner time:
   - the owner interview and time log;
   - the egress rule;
   - a decision on the development-seat licence;
   - the default-assumptions table;
   - a start on the catalogue;
   - 6-12 past designs, with known failures marked.

   Draft one scope amendment (1.2.0) covering estimates and proposals.
2. **Shared foundations:** the units extension, the selection read and the bounded face read, the
   catalogue schema and loader, the material-database parser, and the evaluation corpus and
   harness.
3. **The hand-calc MVP (Part 2, Phase 1).** It is the best-grounded idea. Its library is also
   ideation's sizing engine, and its gate (known failures in the top three) is concrete and
   answerable from the owner's own history.
4. **Grounded ideation (Part 1, Tier 1),** alongside or right after, reusing the library, the face
   read, the catalogue and the chat surface.
5. **Both gates.** Neither assistant moves on until its own gate passes.
6. **Write work, only after 004's stage 1 has run on a real part:** template copy-and-drive
   (Tier 2) and the Simulation study on a copy (Phase 3b), both under the one sandbox-authoring
   amendment shared with 012. A development-seat licence would shorten this step from months to
   weeks.
7. **Later:** Part 2's Phase 2 (dynamics, fatigue, drives). The hand-calc library then becomes the
   checker for concept parts: every concept Tier 2 produces is estimated under the engineer's load
   cases before it is shown.

---

## Open questions for the owner

1. **Is either idea wanted, and which first?** The recommendation is the hand-calc MVP first or
   alongside grounded ideation, with no write work until 004's stage 1 has run.
2. **One scope amendment (1.2.0)** covering both "engineering estimates" and "ideas and concept
   proposals"?
3. **Where each assistant lives.** A Loads mode and an ideation mode in Review (recommended), a
   fifth tab, or the command line first?
4. **A development-seat licence.** Should it be priced with the reseller? It is the biggest
   schedule lever for every write step.
5. **The data-egress rule.** Paid tiers only? What should OpenAI's `store` setting and retention
   be? Is code-only mode for export-marked documents enough? What do customer NDAs and vendor CAD
   terms allow?
6. **The default-assumptions table.** Bolt class, friction, tightening factor, target safety
   factors (static, fatigue, slip), dynamic factors, and whether threads sit in the shear plane by
   default.
7. **Materials.** Which material database does the seat use, and should there be an owner
   override table?
8. **Past designs.** 6-10 for the hand-calc gate (at least 3 known failures, at least 3 known-good
   designs) and 8-12 concept tasks. Can one set serve both?
9. **The catalogue.** Which bought motors, gearboxes, bearings, guides and fasteners go in first,
   and from which licence-clean sources?
10. **References.** Which editions of Shigley, Roark's and Machinery's Handbook does the owner
    have, and a copy of VDI 2230? The validation cases cite them.
11. **Simulation.** Is SOLIDWORKS Simulation licensed on the seat? This only matters for Phase
    3b.
12. **The record shape.** Finding plus Calculation with `estimate.*` (recommended), or a new
    record?
13. **The workflow interview.** A 1-2 hour talk and a two-week time log: how ideas start today,
    where the hours go, and which part families recur. This picks Tier 2's first family and the
    success measure.
