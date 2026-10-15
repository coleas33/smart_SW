# Native entry and pane integration slice

Authorized by the owner's continuation of Feature 016 after the offline gate.
This slice implements selection-assisted entry and review attachment. Workstation
calibration, native freshness verification and cross-extraction rebinding remain gates.

## User flow

The existing Review page gains a saved-evidence context panel. The engineer extracts
context evidence without starting a provider, selects a component or face, enters a
requirement or total force, inspects its target/values/frame/provenance and confirms
the exact revision. “Review with this context” uses that same saved package and an
explicit context/head attachment. Ordinary Review continues its existing behavior.

Host-owned prepared run IDs identify packages; the page never chooses CAD or store
paths. The backend keeps context under `run_root/.engineering-context/<run_id>`,
outside the extracted package and source CAD directories. All writes use the existing
revision/CAS and confirmation helpers. Missing source inputs remain unknown.

## Native observation boundary

A read-only application-thread adapter observes exactly one selection across all
marks. It supports a resolved component or an owning-part face at one exact occurrence.
It checks root document/configuration before and after; records root/owner dirty and
read-only reliability observations; and refuses unknown, dirty or changed state,
unloaded owners, unsupported/multiple selections and ambiguous/missing saved targets.
It does not activate, select, clear, zoom, open, rebuild or resolve lightweight parts.
The adapter caps the saved package at 64 MiB, ancestry walks at 64 and relevant identity
candidates at 256. Exceeding a bound returns unresolved without accepting partial coverage.

Native identity comparisons use the persistent-reference codec and guarded native
comparison in the producing scope. Indeterminate comparisons retain their uncertainty.
Occurrence identity is distinct from part-face identity. The original assembly face
supplies its occurrence before mapping it to the part. Referenced occurrence config
and owning document active config remain distinct. Root-relative transforms apply once.
Only a unique matched saved entity may prefill an entry; anchors and force frames are
built from the saved package, without copying observed native geometry into CAD facts.

Selection observations are explicitly uncalibrated (`native_calibrated: false`), with
`native_model_state: selection_observation_only` and `freshness: cannot_establish`.
The evidence schema has no saved CAD content/dirty attestation, so clean state and
matching entity identity cannot establish unchanged historical geometry. Neither a
selection nor a context approval certifies live CAD state. No existing capability
switch changes; no bridge command or LLM writer is added.

## Offline acceptance gate

- Preparing context creates a package and context without a model/provider request.
- Native capture uses exactly one selection and one scoped match; repeated instances,
  different configs, missing faces and unstable/dirty sources never fall back to a name.
- COM reads pass through the existing guard on the application thread; selection writes
  are absent. Fake interop tests verify calls and failure paths without starting CAD.
- Authenticated context routes accept run IDs and typed inputs, never arbitrary paths.
  Stale heads/digests, source-package changes, malformed input and busy reviews are refused.
- The operator preview includes engineering values and meaningful target/frame/provenance
  labels. Paths, native reference bytes and actor history stay behind the API boundary.
- The page renders hostile strings as text; empty force values remain unknown, not zero.
- Context review requires exact package SHA/context ID/head digest before provider setup;
  ordinary reviews and default model tool schemas retain their behavior.
- A checks-first package update refreshes the opening/saved context summary, preserving
  historical decisions while marking changed evidence applicability as needing review.
- Release compilation, extractor/add-in fake suites, Python nonlive tests and Ruff pass.

## Workstation gate still required

Test selected part/component/assembly faces, native persistent-reference identity,
repeated/nested occurrences and configurations, dirty/read-only sources, active-document
switches and unchanged focus/selection on the SOLIDWORKS machine. Record results before
claiming calibrated selection, native freshness or allowing cross-extraction approval
carry-forward. Drawing generation and structural analysis remain later features.

Use fictional disposable CAD copies for this gate. Record the branch/commit,
SOLIDWORKS version, active and referenced configurations, selected occurrence and
reason codes for each case:

1. Prepare saved evidence; verify no review/provider starts. Enter one requirement and
   one force, inspect the frame/vector/point, confirm, then review with that context.
   Verify the host reuses the prepared run and the model sees recorded decision states.
2. Select one resolved component, a part face and an assembly-context face included in
   the package. Repeat with two instances of the same part, nested instances and differing
   referenced configurations. A face absent from the extraction remains unresolved.
3. Try empty/multiple/unsupported selections, dirty root/owner, unsaved documents,
   unloaded/lightweight ancestry and read-only documents that discard edits. Refusals
   must leave selection, focus, active configuration and native document state unchanged.
4. Switch active document/configuration or change the package after preparation.
   Selection/review reuse must expire; stale head/record/dependency confirmations must
   fail without altering the private history. Editing a confirmed value requires a
   new confirmation; an unknown magnitude remains unknown and cannot be confirmed.
5. Verify persisted IDs against scoped native comparison, including equivalent entities
   with different reference bytes. Ambiguous, missing or indeterminate candidates must
   remain unresolved. Save logs/results, without promoting the adapter to calibrated
   or the context to current-geometry verified merely because these reads succeeded.

## API references

The adapter reuses the existing gated persistent-reference service. SOLIDWORKS'
[reference-comparison example](https://help.solidworks.com/2024/English/api/sldworksapi/Compare_Selected_Objects_and_Their_Persistent_Reference_IDs_Example_VB.htm)
defines 1 as the same identity, 0 as different and -1 as unable to determine.
The [owning-component documentation](https://help.solidworks.com/2024/english/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IEntity~IGetComponent2.html)
requires the original assembly-context entity; the
[corresponding-entity documentation](https://help.solidworks.com/2019/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~GetCorrespondingEntity2.html)
maps that entity into its underlying part/subassembly. The recorded 2024 interop
surface confirms the methods used here. These references inform the adapter;
they do not replace the pending workstation tests of face scope and identity.

The [parent-component documentation](https://help.solidworks.com/2024/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IComponent2~GetParent.html)
specifies null for root/top-level components. The adapter checks a bounded ancestor
chain without loading or resolving anything, and repeats the observation before
accepting a saved-target match.
