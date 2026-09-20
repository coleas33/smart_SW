# Project status and next steps — 2026-09-20

The project is in pilot validation. Handoff fixes U1–U6 are implemented, together
with automatic context, review preparation, and standards attachment.
Live CAD/provider validation and U7 remain;
the pilot observations below are preserved as the original baseline.

This document summarizes `smart_SW-handoff-2026-09-20.zip` and the subsequent
development work authorized by the owner. The original handoff documents and
evidence remain unchanged.

## Development follow-up

- **U1–U3 implemented:** Reserved space for finding Details and scroll the opened
  Details into view; follow-up sends unfold the transcript and reveal the answer.
  The backend's complete Not-examined warning now wraps above Start here and clears
  when a new review is requested.
- **U4 implemented:** The pane receives the bridge's remodel-seat availability
  and disables planning/execution while it is unknown or unavailable. The host
  also refuses those requests before invoking the pipeline.
- **U6 implemented:** Attention records replace a completed temporary file;
  chats stay running until final report writes finish so retries cannot
  overwrite a new session with the predecessor's record. The scan excludes ordinary
  description strings from the stage-1 `IDimension` scan while retaining code
  references and interpolated strings.
- **Verification:** 6,761 Python tests passed (3 skipped, 6 live tests deselected),
  1,843 extractor tests passed, and 1,277 add-in tests passed. Python lint passed.
  The real WebView2 regression uses a 300×600 viewport and checks visible finding
  Details, the full warning, and follow-up placement; it reproduced zero visible
  Details pixels before the scroll fix. Retry tests hold the final render open
  to verify that a new session cannot race the predecessor's writes.
  No live SOLIDWORKS probes or provider calls were run in this development pass.
- **Automatic context:** The opening user message includes a deterministic brief,
  capped at 6,000 UTF-8 bytes. It names document kind/configuration, materials and
  provenance, component hierarchy/load states, extracted mate connections, and evidence
  gaps. Row counts reflect what actually fits, with omitted counts and query guidance.
  No extra model call is needed. The imported pilot Review brief is about 2.1 KB.
- **Review preparation:** Before extraction, the pane reads the component tree without
  writing files or calling a provider. Unread components/gaps offer Check again, Review
  available evidence, or Cancel; complete trees proceed directly. The host validates a
  single-use preparation ID against the active document/configuration. Components are
  still resolved manually in SOLIDWORKS; no mutating resolve command was added.
- **Standards in Review:** The configured Standards profile now reaches the review
  backend automatically. A valid profile offers the standards tool; unavailable profile
  evidence becomes a visible coverage gap, including with the procedural gate disabled.
- **U5 implemented:** One bounded, tool-free request explains the top findings using
  their existing evidence and component names. Text is persisted and shared by Start
  here, matching finding cards, and the report. Unchanged follow-ups reuse it. The
  request uses an isolated provider, low effort, a 2,048-token output ceiling, and a
  16,000-byte input cap; its usage and elapsed time count toward the review. Stop/failure
  suppress generation, and absent/invalid prose produces an explicit fallback.
- **Current-batch verification:** 6,790 Python tests passed (3 skipped, 6 live tests
  deselected), and 1,288 add-in tests passed, including real WebView2 preparation and
  narrow-pane rendering checks. After the final imported-filename privacy and late-Stop
  fixes, 131 focused context, explanation, and chat tests passed; Python lint and the
  whitespace check passed. These
  results validate local behavior, not live provider prose or SOLIDWORKS extraction.
- **Efficiency adoption remains pending:** No flag defaults changed. There is no
  second real held-out package in this checkout: the imported dumps all concern the
  same assembly, the runnable fixture is not held out, and the RMS native folder holds
  a recipe rather than a dumped real part. A different package and an engineer-checked
  answer key are needed for the parallel-tool study. Payload bounds are not measured
  token savings; future comparisons must use the same code and presentation settings.
- **Still next:** Live verification of this batch; associated drawing/BOM discovery;
  a tested, explicitly selected component-resolution action; real-part remodel dry
  runs and CLI probes before enabling the remodel execution capability. No live CAD
  mutation or paid provider call was made during this implementation.

## Pre-test readiness batch

The owner authorized a final implementation batch before live testing. Its scope and
acceptance checks are in [the plan](pretest-readiness-plan-2026-09-20.md), and installation,
test scenarios, benchmark commands, and result collection are in
[the testing handoff](testing-handoff-2026-09-20.md).

- **Remodel preflight:** The runner now validates an attested, planned copy with acceptable
  scope and calibrated stage-1 tolerances before constructing a provider or applying
  changes. Verification reuses the same tolerance rule; no calibration is assumed.
- **Comparable benchmarks:** `review` and `benchmark run` accept `--explain-findings`.
  Legacy CLI defaults stay off; using the flag in both arms includes the pane's explanation
  overhead. Provenance/session disagreement and mixed explanation modes or step budgets
  are refused. The generated ledger shows explanation mode.
- **Compact discovery experiment:** `--lever compact_queries` offers paginated component,
  face, hole, mate, and fastener discovery with bounded output and explicit omissions.
  Full detail remains available through the existing tools. The experiment defaults off;
  its token savings and review quality still require measurement.
- **Local result collection:** `swreview handoff` creates a new allowlisted ZIP with a
  manifest of build identity, settings, usage, coverage, hashes, missing artifacts, and
  redactions. It excludes machine settings and native CAD, masks known credentials,
  refuses overwrite/escaping artifacts, and keeps real-design evidence local.
- **Testing branch:** `codex/pretest-readiness-2026-09-20` includes this batch and the
  preceding handoff fixes. Follow the testing handoff to install this branch on the
  workstation; an update that pulls only `main` will not include these changes.
- **Final local verification:** 6,829 Python tests passed (4 skipped, 6 live tests
  deselected); 1,843 extractor and 1,288 add-in tests passed. Python lint and the
  whitespace check passed. The artifact audit found no occurrence of the CI sentinel
  credential in 10,267 generated files. The test suite retains explicit uncalibrated
  remodel refusals; lifecycle tests use a calibrated fake profile. No live CAD probes,
  paid reviews, tolerance calibration, or efficiency-default adoption was performed.

## Original pilot baseline

- **Development checkout at import:** `main`, commit `e04c027` (`CLI contract:
  the probe remodel verb`), with a clean working tree before this import.
- **Pilot baseline reported in the packet:** `local` commit `c36f183`, containing
  `main` at `e04c027`; SOLIDWORKS 2024; OpenAI `gpt-5.6-luna`, high effort.
- **Available in this baseline:** the reworked Review, Model check, and Standards
  tabs; lightweight-component coverage reporting; and the CLI remodel probe
  command with fifteen probe bodies. The pilot did not run those CLI probes.
- **Review problems reported:** Start-here cards leave finding Details in a tiny
  viewport; folded transcripts hide follow-up answers; the header badge clips
  the lightweight-component warning. The backend produced the findings and answer.
- **Remodel:** the pane's bridge still has no remodel seat. Its refusal is not
  evidence about the separate CLI probe results.
- **Coverage:** two dowel-pin instances remained lightweight. Missing geometry
  leaves fit, stack, and alignment unresolved; an empty interference result does
  not establish a clean assembly.
- **Efficiency:** all pane levers remained off. Review used 1,538,990 tokens over
  38 rounds versus the earlier 1,215,720 over 32 rounds (about 27% more). The
  packet provides no basis to enable the pane's parallel-tool default.
- **Reported validation:** the workstation update stopped at pytest. One
  attention-retry test failed once and passed on rerun; an `IDimension` source
  scan failed on a documentation string. The later C# runs reportedly passed
  1,843 extractor and 1,266 add-in tests. These results were not rerun on import.
- **Testing handoff:** the packet says the pilot seat has finished testing.
  Further implementation and verification belong on the development machine or
  a future testing seat.

## Prioritized next steps

These are the packet's priorities. U1–U6 are implemented as described above;
U7 and live verification remain future work.

| Priority | Work | Completion evidence requested by the packet |
|---|---|---|
| U1 | Cap the Start-here area and reserve usable transcript height. | At a 300×600 pane size, selecting the first card opens readable Details. |
| U2 | Reveal follow-up questions and answers when the transcript is folded. | A follow-up answer is visible and scrolled into view. |
| U3 | Show the full, wrapping Not-examined sentence above Start here on Review. | A two-lightweight-component package shows the warning at 300 px width. |
| U4 | Refuse Remodel before Start when the bridge has no remodel seat. | The unavailable action is explained before a failing bridge call. |
| U5 | Add short LLM-authored explanations of what each prioritized finding means for this model. | The same explanation appears in Start here, the matching finding card, and the report, preserving uncertainty and the existing ranking. |
| U6 | Fix the attention-retry flake and the `IDimension` scan's documentation-string false positive. | The named checks pass through the normal update gate. |
| U7 | Later, validate a held-out design before any pane parallel-tool default change; complete CLI remodel probes and real-profile Standards testing. | Evidence from another design, a CLI probe ledger, and Standards results with the real profile. |

Also outstanding in the packet: the resolved-pin comparison (Task E), Model check
for that sitting, and Tasks B/C/D. The earlier
[workstation handover](workstation-handover-2026-09-20.md) describes those tasks;
the new findings record what actually ran and what remains missing.

## Imported files and evidence

All 18 files from the ZIP were copied without content changes, removing only its
outer `smart_SW-handoff-2026-09-20/` directory so the original relative paths work.

- [Original handoff overview](../README-START-HERE.md).
- [Detailed findings and U1–U7 recommendations](pane-findings-2026-09-20.md).
- [Review report](../dumps/20260919-184136-810-11249/report.md), with the package,
  session, attention record, and event stream alongside it.
- [First Standards report](../dumps/20260919-184738-810-11249-standards/report.md)
  and [later Standards report](../dumps/20260919-184809-810-11249-standards/report.md),
  each with its package, session, attention record, and check result.
- [Remodel refusal log](../logs/tool-service-20260919-184725.log).

The three dump directories and the log are local, Git-ignored evidence because
they contain real-design paths. Their links work in this imported checkout; a
fresh clone needs the original packet. Documentation remains available to track.
API keys, pane settings, and the real standards profile were not in the ZIP.
