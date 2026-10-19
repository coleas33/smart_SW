# SOLIDWORKS Agentic Design Review Pilot

**Revision: Complete consolidated README.** This version combines the original pilot detail, agentic review beginning on day one, and assessments of all 11 linked repositories. Repository research snapshot: September 13, 2026.

Build an AI assistant that investigates drawings and assemblies, gathers engineering evidence, and reports actionable issues. The first objective is to reduce drawing review effort and catch assembly fit-up problems across a broad range of mechanical designs.

Start agentic review on day one, with a small connection to SOLIDWORKS in the first week. Let real investigations identify which additional tools are worth building. The expanded scope below preserves the original opportunities; the implementation sequence brings agentic investigation and targeted CAD access earlier.

The highest-value pilot is an assistant that investigates drawings and assembly interfaces, gathers measurements, and produces findings an engineer can verify quickly. Existing macros remain useful tools the agent can call. The agent chooses the investigation; CAD tools and checked calculations supply the numerical evidence.

**Status:** Proposed pilot. No CAD connector or review application has been implemented or validated in this conversation. The repositories below were inspected through their documentation, file trees, and selected source files. They have not been installed or tested against your SOLIDWORKS 2024 workstation or EPDM vault. Integration effort, ROI rankings, and the recommended combination are judgments to test during the pilot.

## Contents

- [Goals and constraints](#goals-and-constraints)
- [Recommended approach and early agentic review](#recommended-approach-and-early-agentic-review)
- [Opportunities in order of initial ROI](#opportunities-in-order-of-initial-roi)
- [Where all 11 repositories fit](#where-all-11-repositories-fit)
- [Source findings that change the implementation choice](#source-findings-that-change-the-implementation-choice)
- [Minimum CAD tool set and existing SOLIDWORKS capabilities](#minimum-cad-tool-set-and-existing-solidworks-capabilities)
- [Recommended first implementation](#recommended-first-implementation)
- [Example investigation and report](#example-investigation-and-report)
- [Review requirements and boundaries](#review-requirements-and-boundaries)
- [Four-week plan with early agents](#four-week-plan-with-early-agents)
- [Success criteria and ROI](#success-criteria-and-roi)
- [Repository snapshots and reuse notes](#repository-snapshots-and-reuse-notes)
- [Immediate next actions](#immediate-next-actions)

## Goals and constraints

| Item | Requirement |
| --- | --- |
| CAD environment | SOLIDWORKS 2024 and EPDM |
| Design scope | Mixed machined parts, sheet metal, weldments, mechanisms, purchased components, and robotics assemblies |
| Main time sinks | Drawings, tolerance review, and interference checking |
| Main quality problem | Assembly fit-up and tolerance issues |
| Existing work | Attempts at automated drawings and a macro standards checker |
| Development owner | A mechanical engineer; specialist API support is an option |
| Pilot target | A useful result within four weeks of work |
| Productivity target | At least 60 minutes of net engineering effort saved per design |

For planning, “one design” means an assembly or subassembly and its drawing package. Confirm that definition before measuring results. The location and consistency of manufacturing tolerances remain open questions. Establish which sources govern each interface before interpreting fit results.

## Recommended approach and early agentic review

Use an agent that chooses what to investigate, supported by a small set of reliable CAD tools and a mandatory review checklist. The agent can retrieve additional evidence and change its investigation as it discovers potential problems.

A conventional macro follows predefined steps. An agent can identify a suspicious interface, inspect its drawings, request measurements, and pursue a possible failure mode. This distinction follows the workflow-versus-agent model described in [Anthropic's agent design guidance](https://www.anthropic.com/engineering/building-effective-agents).

| Approach | Value | Limitation and pilot role |
| --- | --- | --- |
| Review exported drawings, assembly views, BOM, and requirements | Fastest way to test whether the agent produces useful findings | Coverage is limited to supplied information. Use immediately while connecting native CAD access |
| Let an agent operate the SOLIDWORKS desktop | Can use existing commands through mouse and keyboard interaction | Selection errors, dialogs, and navigation limit repeatability. Use for specific missing operations with inspectable results |
| Connect the agent to CAD data and provide images | Preferred pilot architecture: numerical data plus visual context | Requires a connector on the SOLIDWORKS workstation. Establish a small connection during week one |

Start with the review package available today and add CAD access where missing information materially limits a real investigation. Keep geometry measurements, unit conversions, and established calculation methods in checked software functions. Use AI for investigation, interpretation, explanations, and proposed follow-up checks.

Begin with one agent, a short engineering review instruction, drawings, assembly context, and a few inspection tools. On day one, have it inspect a real package, identify suspicious interfaces, ask for the evidence it needs, and produce a review report. Start connecting native CAD access immediately; use exported files while that connection is being established.

An agentic investigation might follow a blind tapped hole from an assembly view to the screw specification, then to the housing drawing, then request a depth measurement. That sequence can vary with the design. It does not require a dedicated macro for every possible assembly.

| Responsibility | How to implement it initially |
| --- | --- |
| Choose what to investigate next | Agent follows functional requirements and a mandatory review checklist |
| Find documents and understand context | Drawing PDFs, BOM, manually confirmed EPDM version/configuration manifest, and native inspection where available |
| Read or measure geometry | Existing SOLIDWORKS commands, a small CLI/MCP connection, or validated STEP inspection |
| Evaluate a fit or stack | Checked calculation using explicit dimensions, tolerances, units, and assumptions |
| Explain findings | Agent produces evidence, affected instances, calculation, uncertainty, and suggested action |
| Decide acceptance | Engineer reviews the evidence and dispositions findings |

MCP is a protocol for exposing tools to an agent. A CLI can expose the same useful operations without MCP. Neither the protocol nor an agent skill supplies an engineering checker by itself.

**First-week objective:** complete a useful investigation on a real assembly and drawing package, including at least one numerical check the engineer can independently reproduce. A functioning chat window or a generated part is not the pilot outcome.

## Opportunities in order of initial ROI

This ranking reflects the stated time sinks and four-week constraint. Effort ranges are rough estimates for a reusable, narrowly scoped pilot capability, not measured performance or promises of full automation. An initial agent investigation can start sooner. Savings overlap and must not be added together; the full capability list exceeds four weeks.

| Rank | Capability | Initial scope | Rough standalone pilot effort | First use |
| --- | --- | --- | --- | --- |
| 1 | Agentic drawing and interface review | Gather relevant drawings, identify specific problems or missing manufacturing inputs, investigate suspicious interfaces, and navigate directly to findings | 1–2 weeks | First review on day 1 |
| 2 | Interference and clearance review | Check selected component pairs/configurations, group repeated findings, retain reviewed exceptions, and identify changed conditions | 1–2 weeks | Basic measurement during week 1 |
| 3 | Guided fit and tolerance checks | Selected diameter fits, axial stacks, and gaps using confirmed manufacturing tolerances | 2–4 weeks | One simple check in week 1; expand in weeks 2–3 |
| 4 | Fastener and hole compatibility | Screw bottoming, usable thread engagement, thread compatibility, and head/washer clearance for supported hardware | 2–4 weeks | One supported joint type when its inputs are available |
| 5 | Drawing finishing and standards work | Reuse reliable finishing macros; automate repetitive corrections, preparation, and standards checks identified by the baseline | 1–2 weeks | Reuse existing tools immediately; expand selectively |
| 6 | Engineering change impact | Identify affected drawings and mating interfaces when parts, revisions, or configurations change | 2–4 weeks | After document and instance identity is reliable |
| 7 | Tool access, insertion, and motion | Selected wrench/socket envelopes, straightforward installation/removal paths, and specified mechanism positions | 2–4 weeks | Narrow pilot extension or next phase |

Agentic investigation can span all these categories. Each automated conclusion still needs sufficient evidence. Drawing review and drawing finishing are separated here to expose their different implementation work. If existing drawing tools already cover finishing well, devote that development time to guided fit checks and assembly review.

The highest-return implementation work is likely to be reliable evidence retrieval and faster disposition of useful findings. General text-to-CAD generation is a separate productivity opportunity, particularly for fixtures and concept variants, but its value must be measured against these review priorities.

## Where all 11 repositories fit

The pasted links contained joined URLs and a duplicate Graph-CAD entry. All 11 unique repositories are included below. “Now” means worth evaluating in the first week, not a claim of production readiness.

| Repository | What it provides | Fit in this pilot | Priority and remaining work |
| --- | --- | --- | --- |
| [arthurle3210/SwpilotCLI](https://github.com/arthurle3210/SwpilotCLI) | SOLIDWORKS Task Pane integration, an agent-driven C# tool workflow, screenshots, and existing drawing/assembly inspection programs | Strong first candidate for native inspection. Start with relevant console tools; the full embedded UI can wait | **Now: primary connection candidate.** Fix the data issues below and verify SW 2024 operation. Custom license matters for reuse |
| [delancy827/solidworks-skills](https://github.com/delancy827/solidworks-skills) | SOLIDWORKS skills, COM automation lessons, MCP code, screenshots, and model readback/verification helpers | Reuse selected instructions and connection/inspection patterns to teach the reviewer how to obtain evidence | **Now: instructions and selected helpers.** Add a review-specific checklist; model health checks do not establish manufactured fit |
| [arthurle3210/swapi-pilot-solidworks-mcp](https://github.com/arthurle3210/swapi-pilot-solidworks-mcp) | A documented remote MCP service for API search, member/enum lookup, examples, and C# project templates | API reference assistance when developing missing inspection tools; complements SwpilotCLI | **Now: optional development aid.** This service is documentation access, not the live CAD connection. Remote service operation was not tested |
| [alisamsam/Solidworks-MCP](https://github.com/alisamsam/Solidworks-MCP) | Python/COM MCP server with native document, sketch, feature, unit, and Python execution tools | A smaller alternative connection if a Python/MCP workflow is quicker to establish | **Now: alternate to SwpilotCLI.** Add explicit assembly, drawing, tolerance, and measurement queries; restrict the review tool set |
| [earthtojake/text-to-cad](https://github.com/earthtojake/text-to-cad) | Agent CAD skills and a substantial CAD runtime, including STEP references, measurements, validation, interference inspection, and viewing | Useful supplemental inspection of exported geometry; also a reference for measurable agent investigations | **Now: targeted STEP trial.** Confirm export identity, hierarchy, placement, and units; retain governing native drawings for tolerances |
| [Pan-Chera/Multi-Agent-CAD](https://github.com/Pan-Chera/Multi-Agent-CAD) | LangGraph orchestration for specification planning, geometric planning, code generation, and a CAD generation/QA repair loop | Borrow structured requirements, evidence contracts, bounded retries, and explicit verification states | **Weeks 2–3: selective patterns.** Adapting its generation agents is more work than starting one review agent. Its benchmarks concern generation, not this review task |
| [djlex83/solidworks-automation-skill](https://github.com/djlex83/solidworks-automation-skill) | An agent skill and Python wrappers, mainly for SOLIDWORKS part modeling, selection, and feature operations | Small reusable building blocks and ways to generate simple benchmark fixtures; potential future correction tools | **Selective reuse.** The inspected wrapper is primarily a modeling helper, not an assembly tolerance reviewer |
| [forgent3d/forgent3d-desktop](https://github.com/forgent3d/forgent3d-desktop) | A desktop CAD environment with a Python/build123d runtime, parameterized model packages, a viewer, rebuilds, and MCP feedback | Reference for the agent's inspect/rebuild/view experience; later concept and mechanism experiments | **Later: UI/runtime reference.** Its CAD environment is separate from native SOLIDWORKS/EPDM; the exposed preview tools do not supply drawing or tolerance analysis |
| [Adam-CAD/CADAM](https://github.com/Adam-CAD/CADAM) | Browser-based text/image-to-CAD, OpenSCAD generation, parametric controls, preview, and export | Later fixture/concept generation and an example of an approachable CAD agent interface | **Later: generation/UI.** Native SOLIDWORKS review integration remains to be built; GPL-3.0 differs from the MIT-licensed options |
| [EESJGong/Graph-CAD](https://github.com/EESJGong/Graph-CAD) | Research pipeline from text through a hierarchical graph and action plan to Blender Python code | Inspiration for representing parts, interfaces, and requirements in a review evidence graph | **Later: research reference.** It does not extract a graph from an existing SOLIDWORKS assembly. Its model/Blender pipeline is outside the initial sprint |
| [sina-salim/AI-SolidWorks](https://github.com/sina-salim/AI-SolidWorks) | A local GUI for generating, executing, and debugging SOLIDWORKS VBS scripts | Reference for a simple script-assistant interface | **Low priority for this pilot.** The inspected implementation uses Tkinter and cscript; I did not find a live MCP review server in that implementation. It overlaps with more relevant connection candidates |

## Source findings that change the implementation choice

### SwpilotCLI: useful inspection code needs targeted fixes

The tool catalog includes drawing inspection, dangling-dimension detection, assembly part listing, feature/face listing, and screenshots. These are directly relevant starting points. Its reuse workflow—develop a missing tool, verify it, then register it for future calls—also fits a four-week pilot. [Tool catalog](https://github.com/arthurle3210/SwpilotCLI/blob/5824b367238e4615609aff1edb5253e2420e0333/TOOLS.md).

However, the inspected drawing reader multiplies dimension and tolerance values by 1,000 and labels them as millimeters without separating angular dimensions. It can substitute zero for a missing dimension, formats values to limited decimal precision, and can report an unsupported document through text while the process subsequently exits successfully. Correct these behaviors before using its output in tolerance calculations. The separate dangling-dimension tool does contain angle conversion, so this finding concerns the drawing reader specifically. [Drawing reader source](https://github.com/arthurle3210/SwpilotCLI/blob/5824b367238e4615609aff1edb5253e2420e0333/sup_tools/swpilotcli-inspect-drawing/scripts/InspectDrawing/Program.cs).

Its assembly file list is a starting inventory; the pilot still needs component instance identities, referenced configurations, and transforms. Use explicit source dimensions for review even where upstream modeling examples suggest inferring unclear dimensions.

The repository's custom license states that personal and internal organizational use is free, while redistribution and external service/product uses require the author's permission. Treat that as a reuse constraint, rather than assuming a permissive open-source license. [License](https://github.com/arthurle3210/SwpilotCLI/blob/5824b367238e4615609aff1edb5253e2420e0333/LICENSE).

### The two SOLIDWORKS MCP projects have different jobs

`swapi-pilot-solidworks-mcp` documents an API-reference service. The inspected repository contains documentation and agent instruction files, not the hosted server implementation. Generated code still needs a local execution environment to reach SOLIDWORKS. [Available tools](https://github.com/arthurle3210/swapi-pilot-solidworks-mcp/blob/674204c04505f7253d75bafd080dbf620af2e0cc/README.md).

`alisamsam/Solidworks-MCP` actually exposes native SOLIDWORKS operations through Python/COM. Its generic `execute_python` tool runs Python with access to the application and operating system; it is not a read-only boundary. For review, expose a curated set of inspection operations and validate new tool code on benchmark copies before admitting it to the reusable tool set. [Server implementation](https://github.com/alisamsam/Solidworks-MCP/blob/ee8f42a1a919af5e0fa8d1dcd24270c9983ce027/solidworks_mcp/server.py).

### solidworks-skills: verification means different things

The inspected `full_model_check` marks a model healthy when rebuilding succeeds and the feature count is positive. That is useful application feedback, but it does not establish that a hole fits a shaft or that a drawing specifies an adequate tolerance. Reuse the readback pattern, then add engineering acceptance checks with their own evidence and coverage. [Validator source](https://github.com/delancy827/solidworks-skills/blob/b9314cf133bee1479383f426da712f89032101a0/solidworks-mcp/core/war_validator.py).

### text-to-cad: relevant review tools, with export and coverage limits

This repository now goes well beyond generation. Its inspection workflow includes STEP measurement, alignment, topology validation, and interference checks. It is a credible first-week experiment for agent inspection of exported assemblies. [Inspection reference](https://github.com/earthtojake/text-to-cad/blob/3e4dfdeef2cbd5804c369592b59620132188a150/skills/cad/references/inspection-and-validation.md).

For its interference tool, the threshold is overlap **volume in mm³**, not linear clearance or a manufacturing tolerance. The default is 1 mm³. Hierarchy determines which overlaps are classified as internal to one part and excluded from the failure verdict. Also, the inspected implementation records truncated pair counts without making truncation alone invalidate its overall success flag, and some unsuccessful geometry operations yield no reported clash. A review adapter must report incomplete or failed computations as unresolved. Verify results against SOLIDWORKS on known cases before depending on them. [Interference implementation](https://github.com/earthtojake/text-to-cad/blob/3e4dfdeef2cbd5804c369592b59620132188a150/packages/cadgen/src/cadgen/interference.py).

### Generation frameworks offer patterns, not measured review accuracy

Multi-Agent-CAD provides structured requirements and a bounded generation/QA workflow. Its verification schema defaults upper and lower tolerances to 0.1 mm. A manufacturing reviewer must instead preserve missing tolerance information as unknown until the governing source is found. The authors' generation benchmark results do not predict missed fit-up defects or hours saved here. [Schemas](https://github.com/Pan-Chera/Multi-Agent-CAD/blob/f31a2f65aa1b1e16fa6c45f1d642142fb696db28/multi_agent_cad/schemas.py), [workflow](https://github.com/Pan-Chera/Multi-Agent-CAD/blob/f31a2f65aa1b1e16fa6c45f1d642142fb696db28/multi_agent_cad/graph.py).

Forgent3D's preview MCP exposes model listing, screenshots, and rebuilding. Graph-CAD's inference implementation targets Blender. These can inform an interface or architecture, but the required native drawing, configuration, and tolerance evidence needs another source. [Forgent3D tool definitions](https://github.com/forgent3d/forgent3d-desktop/blob/d538ca46d9c3766a0a21ba73ba88607ef305dedd/packages/shared/src/mcp-tools.ts), [Graph-CAD inference](https://github.com/EESJGong/Graph-CAD/blob/2ffb69836037fb870244477209e8ef5ad02df977/infer_api.py).

## Minimum CAD tool set and existing SOLIDWORKS capabilities

These are capability requirements for the reviewer, not a claim that any single repository implements them all. Begin with the subset needed for the first investigation and add the rest in response to demonstrated gaps.

| Tool capability | Purpose |
| --- | --- |
| Read assembly structure, configurations, and mates | Establish what is present and how it is positioned; distinguish repeated instances and their referenced configurations |
| Retrieve associated drawings and revision information | Identify the documents governing the reviewed condition |
| Read dimensions, tolerances, notes, and features | Gather manufacturing requirements with source references and correct units |
| Measure geometry and run interference checks | Obtain numerical evidence and retain the tested scope/settings |
| Isolate components and create useful views | Help the agent and engineer inspect the same interface and reproduce the finding |
| Run checked calculations | Evaluate explicit limits with consistent units and an identified calculation model |
| Record findings and review coverage | Preserve evidence, assumptions, exceptions, unresolved items, and engineer disposition |

Retain the SOLIDWORKS 2024 [dimension and tolerance API reference](https://help.solidworks.com/2024/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDimension_members.html?format=P&value=) and [interference detection example](https://help.solidworks.com/2024/english/api/sldworksapi/Run_Interference_Detection_Example_VB.htm) as implementation references. These identify relevant native building blocks; they do not establish the accuracy of the complete reviewer. Check the actual behavior of the selected methods on the pilot workstation.

For broader tolerance studies, evaluate [TolAnalyst and its DimXpert input workflow](https://help.solidworks.com/2024/english/SolidWorks/sldworks/c_tolerancing_overview.htm) before building a general solver. Confirm availability and the preparation required for the chosen assemblies. Keep narrow fit calculations available when a full tolerance-analysis setup would exceed the pilot's scope.

## Recommended first implementation

Use an existing agent client with one review instruction and one primary SOLIDWORKS connection. Evaluate SwpilotCLI's relevant console tools first; use alisamsam's MCP server as the alternate if that is faster to establish on the workstation. Borrow selected solidworks-skills guidance. Add swapi-pilot documentation access when it helps tool development, and text-to-cad STEP inspection only where it supplies useful missing evidence.

Run native CAD tool execution on a Windows workstation with SOLIDWORKS 2024 and access to the EPDM working copy. Bind each result to the intended document and configuration. A remote chat session needs that local worker to inspect live native CAD data.

Do not make integration of all these repositories a deliverable. Limit connection setup to about two working days before choosing the simplest working route. While setup proceeds, run real reviews on exported PDFs, BOMs, STEP files, and a manually confirmed configuration/version manifest.

| Needed capability | Starting material | Work still required for this pilot |
| --- | --- | --- |
| Drawing inspection | SwpilotCLI drawing tools plus PDFs | Correct units/errors; preserve tolerance type, full values, sheet/view identity, and source location; confirm omitted annotations |
| Assembly context | Native document/part tools | Component instance IDs, transforms, referenced configurations, suppression/loading state, and relevant mates |
| Document authority | EPDM and supplied review package | Record exact vault file/version, revision, configuration, local modifications, and export provenance; automate retrieval after proving value |
| Numerical geometry checks | SOLIDWORKS measurements/interference; optional STEP tools | Selected pairs and configurations, explicit units/settings, complete/error status, and comparison against known cases |
| Fit and tolerance calculations | A small checked calculation function | Governing input references, sign conventions, limiting cases, and explicit assumptions; missing input must stay unknown |
| Agent report | Existing agent client | Finding schema, evidence links, coverage, engineer disposition, and time measurement |

I did not find a demonstrated, complete SOLIDWORKS 2024 + EPDM fit/tolerance review workflow in the inspected material. These projects can reduce connector, instruction, and interface work; the evidence model and application-specific validation remain the central build.

A second agent can later challenge findings or review coverage if it measurably improves quality. Agreement between agents is not a substitute for independent geometry or calculation evidence. Start with one reviewer so the pilot measures engineering value before adding orchestration complexity.

## Example investigation and report

For a bolted cover with blind tapped holes, the agent could:

1. Identify the cover, housing, screws, and washers, including the affected component instances.
2. Retrieve the governing drawings and configuration information.
3. Inspect screw length, cover thickness, counterbores, washer stack, and usable thread depth.
4. Investigate whether a screw could bottom before the cover clamps.
5. Calculate limiting conditions using confirmed dimensions and tolerances in a checked calculation.
6. Highlight affected components and cite the inputs supporting the finding.
7. Request clarification when an input is missing, such as usable thread depth when only drill depth is specified.

The investigation is assembled from generic tools and engineering instructions. It does not require a dedicated macro for that exact cover design.

If only drill depth is available, usable thread depth remains unresolved. The agent can request the missing source or propose a targeted inspection. It should not infer a favorable value and clear the assembly.

Each finding should contain:

- Affected component instances and drawing sheet/view or annotation.
- File version, revision, configuration, and export identity where applicable.
- Observed condition, governing requirement, and source dimensions with units/tolerances.
- Tool result or calculation, including assumptions and coverage limits.
- Status: demonstrated issue, suspected issue, unresolved, or checked within stated scope.
- Recommended next action and the engineer's eventual disposition.

## Review requirements and boundaries

- **Use governing manufacturing inputs.** Nominal CAD geometry alone cannot establish manufactured fit. Identify the correct drawing, configuration, tolerances, and applicable general notes.
- **Confirm intent.** Mates do not fully describe assembly sequence, allowable movement, required fit, or functional acceptance criteria.
- **Show the calculation model.** A size-only fit result does not automatically account for positional error, form, coatings, temperature, or deformation. State what the model includes.
- **Make findings inspectable.** Identify the components or drawing location, source inputs, assumptions, reasoning, and recommended next action.
- **Track coverage.** Record what was checked, skipped, unresolved, or outside scope. Distinguish a demonstrated issue from a hypothesis requiring review.
- **Revisit exceptions when conditions change.** Intentional interference must be tied to the reviewed geometry and configuration. Avoid blanket exclusions that could hide defects.
- **Treat motion coverage explicitly.** Checking selected positions does not establish clearance throughout an entire motion path.
- **Check meaningful drawing requirements.** Requiring every modeling dimension to appear on a drawing is not a valid completeness test.
- **Preserve incomplete and failed results.** Keep unsupported, missing, truncated, and failed checks visible. A successful API call or a healthy model is not an engineering acceptance result.

The first pilot produces review findings. Autonomous GD&T creation, general drawing dimensioning, and structural approval would require separate scope and validation.

## Four-week plan with early agents

| When | Work | Evidence of progress |
| --- | --- | --- |
| Day 1 | Select the first real package, establish a human baseline, and run an agent investigation with existing exports and review instructions | An evidence-linked draft finding or a precise missing-input request; initial supervision time |
| Days 2–3 | Establish one native connection; verify document identity, dimension units, screenshots, and error behavior on known examples | Agent retrieves correct data from the intended SW 2024 document/configuration |
| Days 4–5 | Complete a drawing/interface review and one targeted interference or simple fit investigation; compare numerical results with the engineer | A reproducible useful investigation and a ranked list of remaining data/tool gaps |
| Week 2 | Extend only the most valuable queries; improve source/instance identity and narrow fit calculations; reuse relevant standards macros | Less manual evidence gathering and fewer unsupported findings |
| Week 3 | Improve high-value checks, false-alarm handling, exception validity, and report navigation; add a separate critique pass only if useful | Repeatable findings and measured reduction in total reviewer effort |
| Week 4 | Evaluate on held-out packages; measure defects, coverage, and net time; document a continue/narrow/revise/stop decision | Evidence for or against at least 60 minutes saved per design |

Use 5–10 representative packages initially, including known defects and correct designs. Withhold the answer key from the agent and reserve some packages for evaluation. Include diverse mechanical interfaces, such as a shaft/bearing fit, bolted plate stack, and sheet-metal or welded assembly. This is a small pilot, not a statistical reliability claim.

The four-week progression remains: establish the baseline and initial findings; improve evidence access; add reproducible numerical investigations; and evaluate on unfamiliar designs. The schedule above moves the first native queries and narrow numerical checks into week one. Extensive integration follows evidence of value from those early reviews.

## Success criteria and ROI

**Net time saved = baseline engineering effort − assisted engineering effort.**

Count package preparation, recurring setup, supervision, verification, false-alarm handling, corrections, and remaining manual review in assisted effort. Track unattended runtime separately because it can still affect turnaround. Record one-time development cost separately.

Target at least **60 minutes of net savings per design without degrading review quality**. Track valid findings, severity, known defects missed, false alarms, and unresolved coverage. Report the distribution across designs, not only the most successful example.

Four weeks to demonstrate value differs from recovering development cost. Record development hours separately so payback can be computed from measured savings rather than assumed ones. Avoided scrap and rework may improve ROI when supported by actual results.

At the checkpoint, record the decision and its basis: continue if the time savings and review quality justify it; narrow scope if only some checks are useful; revise if retrieval or false alarms dominate effort; or stop if the assistant adds work without enough benefit. A small successful pilot supports further testing, not universal reliability.

## Repository snapshots and reuse notes

These are the inspected default-branch commits on September 13, 2026. Links above identify the projects; the pinned source links and commits below make the assessment reproducible. License entries summarize repository declarations and files, not a dependency-wide license audit.

| Repository | Inspected commit | License/reuse information found |
| --- | --- | --- |
| earthtojake/text-to-cad | [3e4dfdee](https://github.com/earthtojake/text-to-cad/commit/3e4dfdeef2cbd5804c369592b59620132188a150) | MIT at repository root; check bundled components separately |
| Adam-CAD/CADAM | [54f9512a](https://github.com/Adam-CAD/CADAM/commit/54f9512a957f0e51575acf59c82289d758684e4d) | GPL-3.0 |
| Pan-Chera/Multi-Agent-CAD | [f31a2f65](https://github.com/Pan-Chera/Multi-Agent-CAD/commit/f31a2f65aa1b1e16fa6c45f1d642142fb696db28) | MIT; includes a vendored CAD runtime from the text-to-cad ecosystem |
| forgent3d/forgent3d-desktop | [d538ca46](https://github.com/forgent3d/forgent3d-desktop/commit/d538ca46d9c3766a0a21ba73ba88607ef305dedd) | MIT; README download links point to the separate forgent3d/forgent3d release repository |
| EESJGong/Graph-CAD | [2ffb6983](https://github.com/EESJGong/Graph-CAD/commit/2ffb69836037fb870244477209e8ef5ad02df977) | No LICENSE file found in the inspected tree; external model weights are another dependency |
| alisamsam/Solidworks-MCP | [ee8f42a1](https://github.com/alisamsam/Solidworks-MCP/commit/ee8f42a1a919af5e0fa8d1dcd24270c9983ce027) | MIT |
| delancy827/solidworks-skills | [b9314cf1](https://github.com/delancy827/solidworks-skills/commit/b9314cf133bee1479383f426da712f89032101a0) | MIT |
| arthurle3210/swapi-pilot-solidworks-mcp | [674204c0](https://github.com/arthurle3210/swapi-pilot-solidworks-mcp/commit/674204c04505f7253d75bafd080dbf620af2e0cc) | Documentation repository; no LICENSE/server implementation found in the inspected tree; hosted service terms require a separate check |
| arthurle3210/SwpilotCLI | [5824b367](https://github.com/arthurle3210/SwpilotCLI/commit/5824b367238e4615609aff1edb5253e2420e0333) | Custom license; internal organizational use stated as free; external uses/redistribution restricted |
| sina-salim/AI-SolidWorks | [fe9a1611](https://github.com/sina-salim/AI-SolidWorks/commit/fe9a1611ef97b8bbb7b0ff246cbb2529da59b84b) | README claims MIT, but no LICENSE file found in the inspected tree |
| djlex83/solidworks-automation-skill | [522b0d1d](https://github.com/djlex83/solidworks-automation-skill/commit/522b0d1d340c426e187f0357f45780eac3fd2abd) | MIT |

## Immediate next actions

1. Confirm where manufacturing tolerances are stored and how consistently they are recorded.
2. Select the initial benchmark packages and prepare an answer key withheld from the agent. Pick one small representative assembly to start; record its configuration and EPDM versions.
3. Time a normal human review, then run the first agent review immediately on the exported package while establishing the chosen native connection.
4. Use the first investigation's missing evidence to select the next tool to build. Commit to extensive CAD integration only after the early reviews show where it will save effort.
5. Compare against existing macros and, if practical, a commercial reviewer on the same benchmark.

[CoLab AutoReview](https://www.colabsoftware.com/product/autoreview) advertises review of CAD models and drawings, including drawing completeness, dimensional/tolerance inconsistencies, and design feedback. Use it as a buy-versus-build comparison if access fits the pilot schedule. Its performance on these specific assemblies remains to be demonstrated; compare setup effort, missed defects, false alarms, evidence quality, and total engineer time using the same held-out packages.

**Existing review reminder:** October 3, 2026. This is the checkpoint already scheduled during the discussion; the actual pilot start date has not been confirmed.
