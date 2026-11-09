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

The next sitting is **S1, Start readiness** (decision 167A, since 2026-10-31): about three hours,
with no key and no paid call, for Remodel Start's evidence.

1. Open the plan's section [S1: Start readiness](workstation-test-plan.md#s1-start-readiness) and
   check its **Before the sitting** list first. Stop and tell the engineer if anything on it is
   missing.
2. Run S1's table in order, each step as the step itself says.
3. Fill the results sheet as each step ends (step 1.4 copies it into the handover folder).

The plan's sections "The next sitting: where 2026-09-26 stopped" and "First: the retest of
2026-09-28's findings" describe the two-day sitting S1 replaced. Do not start from them; S1's table
names the steps it takes from them.

## Rules for the whole sitting

- **Never commit or paste** the standards profile, the part-roles draft, run folders or logs. They
  hold company data. The results sheet names documents by letter only.
- **Never change the engineer's files.** Every product step is read-only on the vault; the re-modeler
  works only on its own copy.
- **The seat pushes nothing.** The handover folder travels by hand to the development machine.
