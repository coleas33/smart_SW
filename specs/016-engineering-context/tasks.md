# Tasks

- [x] T001 Strict sidecar models and schema contract; invalid/unknown inputs tested.
- [x] T002 Deterministic force units and rigid-frame math.
- [x] T003 Conservative saved-snapshot anchors and binding assessments.
- [x] T004 Immutable revision storage, locking, CAS and failure recovery.
- [x] T005 Record edits and exact-digest explicit confirmation receipts.
- [x] T006 Offline context CLI and explicit review injection.
- [x] T007 Bounded read-only LLM tools and privacy/default-surface regressions.
- [x] T008 End-to-end fixtures, independent review and nonlive regression gate.
- [x] T009 Document offline delivery and the pending native selection gate.
- [ ] T010 Native SOLIDWORKS selection/rebinding and unsaved-state verification
      (future workstation gate; excluded from the offline delivery).
- [x] T011 Bounded guarded selection observation and scoped saved-target matching.
- [x] T012 Authenticated private context routes and exact session attachment.
- [x] T013 Prepare evidence, enter/inspect/confirm and review-with-context pane flow.
- [x] T014 Fake native/backend/WebView regressions, Release compile and full offline gate
      ([final receipt](offline-gate-native-entry.md)).
- [ ] T015 Native selection calibration and source-freshness attestation on the workstation
      (remains pending; no cross-extraction approval carry-forward in this slice).
- [x] T016 Merge `main` (015's send gate) on top of 016 and regenerate the waiting pane
      fixtures with 016's labels, 016 landing second (owner decision 99A; 015 T117 note).
- [x] T017 Context review through 015's one `CreateReviewSession`, Send or Wait from the
      box, and the page's context controls busy while a review waits, sends or is checked
      again (99A; T116 integration review, blocker "the context start skips the Send gate").
- [x] T018 One opening builder input: the summary lives on the review run, so 015's opening
      rebuilt at Send keeps the engineering block, rebuilt over a reloaded package (99A;
      T116 integration review, blocker "the rebuilt Send opening drops the context").
- [x] T019 The waiting record names its attachment, and a restored review's re-run reloads
      and validates it, never unlinking the summary before its commit point (99A; T116
      integration review, "a restored waiting review's re-run drops its engineering context").
- [x] T020 No context edit while a review of the folder is set up or waits for Send: one
      "folder being set up" registry (015's `_pending_run_dirs`) for every start mode, and
      `awaiting_send` counted as busy (99A; T116 integration review, "saved context can be
      edited while a review that carries it waits for Send").
- [x] T021 Final gate on Python 3.11 and 3.12, Release build, .NET and the replay check
      ([receipt](validation.md#adaptation-to-feature-015s-send-gate--2026-10-15)).
- [x] T022 001's review-session schema accepts a finding that names its document scope in a
      non-empty `inputs` (the hygiene checks' root-document findings), and a whole pane
      review's `session.json`, ticked or unticked, with or without context, validates
      (owner decision 109A; no finding reader or writer changed).
- [x] T023 The verifier's two probes kept as tests (ticked and unticked Send with context are
      byte-identical; a re-run with context sends what the live review would have), and
      Remodel's awaiting rule held once (`chat/remodel._awaiting`; the verifier's note).
- [x] T024 Saved inputs stay matched after the review's live interference check rewrites the
      package: the baseline records the package's digest without that check's rows and gaps,
      and binding accepts exactly that rewrite in the check's own spelling; any other change
      is a mismatch (owner decision 107A; the verifier's 29A).
- [x] T025 A re-run or Retry carrying saved context also requires the baseline's package id,
      root document and configuration; its validation stays the head, context id and saved
      package digest (owner decision 105A; the verifier's 26A). The panel's strict lock is
      kept as built (106A; 27A).
- [x] T026 Retry on a failed context review re-attaches the same saved context in its own run
      folder through the one gated `CreateReviewSession`, and a context changed since is
      refused toward the Engineering context panel (owner decision 108A; 30A). The refusal's
      message and the `EngineeringContextConflict` label name an action that exists (the
      verifier's note).
- [x] T027 Final gate for 105A-109A on Python 3.11 and 3.12, Release build, .NET and the
      replay check ([receipt](validation.md#owner-decisions-105a-109a-on-the-adversarial-check--2026-10-15)).
