# Next seat sitting: start here (2026-09-27)

This folder is the **current** test plan for the pilot workstation, the machine with the licensed
SOLIDWORKS 2024 seat. If you are the testing machine's assistant or the engineer running the
sitting, everything you need is in this folder. Older handovers elsewhere in `docs/` are history;
do not follow them.

## Read in this order

1. **This file.**
2. [`workstation-test-plan.md`](workstation-test-plan.md): the sitting, in numbered steps. Each
   step gives the exact command to paste, what to look at, and what counts as pass and fail. **This
   is the authority**: when anything else disagrees, the plan wins.
3. [`workstation-handover.md`](workstation-handover.md): the same sitting as one ordered list, with
   the reasons for the order and what the 2026-09-26 sitting already reached.
4. [`workstation-results.md`](workstation-results.md): the results sheet. The plan's step 1.4 copies
   it into the sitting's handover folder as `pane-findings-<date>.md`; fill it in there as each step
   ends. Do not edit this copy in the repository.
5. [`../workstation-runbook.md`](../workstation-runbook.md): machine setup and health checks, for
   reference.

## Where this sitting starts

- The 2026-09-26 sitting reached steps 1.3, 1.6, 1.7, 2.2 and 2.3 on an older build.
- **This sitting still runs step 1 first**, so the update brings the new build and the gates run. It
  then **continues from step 2.4**. The handover's section "Where the 2026-09-26 sitting stopped"
  says which earlier results carry over.
- *Added 2026-09-28:* **after step 1 and before step 2.4, the retest of the 2026-09-28 sitting's
  findings U25 to U27 comes first**: the plan's step 4.9 (a drawing active) and step 5.3 (crash
  capture, Remodel a copy on a throwaway box, then part J checked in). The plan's section "First:
  the retest" gives the order and what to keep if SOLIDWORKS closes;
  [`../testing-feedback-2026-09-28.md`](../testing-feedback-2026-09-28.md) says what changed.
- New in this build:
  - bought (COTS) parts are told apart from custom parts;
  - findings are grouped by type;
  - labels say "Checked by code" or "AI guidance";
  - the review no longer asks about vault versions;
  - there is an honest drawing offer;
  - the re-modeler has a SOLIDWORKS seat. Plan runs on a copy, and Start stays switched off until
    the blocking probes pass.
- The plan's steps for these are marked with their task ids (013 T141 to T144, T153, 004 T033 to
  T039).

## Rules for the whole sitting

- **Never commit or paste** the standards profile, the part-roles draft, run folders or logs. They
  hold company data. The results sheet names documents by letter only.
- **Never change the engineer's files.** Every product step is read-only on the vault; the re-modeler
  works only on its own copy.
- **The seat pushes nothing.** The handover folder travels by hand to the development machine.
