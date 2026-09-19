# Feature request: resolve lightweight components before a review, by choice

Raised on the pilot workstation, 2026-09-19, from three consecutive runs that graded an
assembly whose two dowel pins were never examined.

**One sentence.** Before a review or a check, show the engineer the components that are
lightweight and let them choose, per component, which to resolve - because sometimes
lightweight is right and sometimes it silently hollows out the whole review.

---

## 1. Why: the evidence from this workstation

`810-11249.SLDASM` is one machined part plus two dowel pins. The pins are the entire
reason the assembly exists: they locate it. On every run today both pin instances were
**lightweight**, and the consequences were large and almost invisible.

**In the Review tab** (`20260919-135032-810-11249`): live interference detection ran and
returned nothing.

```
bridge_interference  ok  0.27 s
{"status":"computed","configuration":"Default","interferences":[],"added_to_package":0,"gaps":[]}
```

The same assembly on 2026-09-18 produced **two `interference.static` findings**. The
package carried **23 extractor gaps**, and twenty coverage rows read

> `doc:08acbc29ab8a: component DOWEL PIN ... lightweight; tree not read`

The headline said nothing. An engineer reading the verdict would not learn that the two
components under review were never read.

**In the Standards tab** (`20260919-135855-810-11249-standards`): seven of sixteen checks
came back unresolved for the same reason, and here the wording is exemplary:

> the pin document is reached only through component instances that are not resolved
> (cmp:0002 is lightweight, cmp:0004 is lightweight), so the evidence this check reads
> was not read from the document; **the reviewer does not resolve, load or open an
> instance to obtain it**

That last clause is the current design, stated deliberately, and it is the right default.
The gap is that the engineer is given no way to change it and re-run.

**The cost.** A review of this assembly is close to worthless while the pins are
lightweight, and nothing tells the engineer to fix it. Reviews are not reproducible either:
the same design, the same commit and the same model give materially different findings
depending on how SOLIDWORKS happened to load the assembly.

---

## 2. What is being asked for

Before the dump, a table of the components the assembly contains that are **not resolved**,
with the engineer choosing which to resolve:

| Component | Instance | State | Resolve? |
|---|---|---|---|
| pin instance | `cmp:0002` | lightweight | [x] |
| pin instance | `cmp:0004` | lightweight | [x] |
| BRACKET, COVER | `cmp:0007` | lightweight | [ ] |

with **Resolve all** / **Resolve none** buttons, and the choice applied before the
extraction that feeds the review.

The point of per-component choice: on a 400-component assembly the engineer genuinely does
not care about most of it, and resolving everything is slow. They care about the handful of
parts at the interface under review. That is a judgement only they can make, which is
exactly why it should be a table and not a global switch.

---

## 3. The boundary this crosses, and the precedent to follow

**Resolving a component is a mutating SOLIDWORKS call.** `SetSuppression2` is on the
`ReadOnlyGuard` denylist, and the comment there is explicit:

> Suppression state changes the geometry a later check would read. `SetSuppression2` and
> `ForceRebuild3` are the two the engineer-run suppress-test is exempted from, and it is
> exempted by building its gate with `SuppressTestGuard`, **never by this list**.

So this feature must not touch the denylist. It needs **its own gate**, built the way
`Program.SuppressTestGate` builds the suppress-test's.

Feature 003's suppress-test is the working precedent for a gated, engineer-authorised
mutation, and its rules should carry over nearly unchanged:

- **Nothing happens without every precondition**, all checked before the first mutating
  call: an explicit acknowledgement from the engineer, the document already open in the
  engineer's session (not opened read-only by us - a read-only document answers `false` to
  every `SetSuppression2` and the run would prove nothing), the expected configuration.
- **The API's answer is never trusted.** Re-read `GetSuppression2` after every write and
  report what the state actually became.
- **Everything attempted is recorded**, including refusals, with the distinct interop
  member names written to a log, as `suppress-test.log` already does.
- **A component that could not be resolved is named**, not silently skipped.

Two differences from the suppress-test worth deciding deliberately:

1. **Direction.** The suppress-test *removes* geometry and must restore it. This
   *adds* geometry. Restoring to lightweight afterwards is therefore optional rather than a
   safety requirement - but see the open question below.
2. **Blast radius.** Resolving a component loads its file and its children. On a large
   assembly that is slow and memory-hungry, which is the reason the per-component table
   exists rather than a blanket resolve.

---

## 4. Where it belongs

Three candidate homes, in preference order:

1. **A pre-flight step on the tab that is about to dump** - Review, Model check and
   Standards all extract first. The table appears when the engineer presses the verb, the
   dump follows the choice. Best fit for the problem: it is exactly the moment the decision
   matters, and it makes the lightweight state impossible to miss.
2. **The Extract tab.** It already exists to prepare an evidence package by hand, and it is
   native WinForms, so no page or proxy work is involved. Smallest change, but only helps
   an engineer who already knows to go there.
3. **A `swreview-extract` console option.** Useful for scripted runs and for the workstation
   harness, and probably wanted eventually regardless, but it does not help the pane user
   who is the one hitting this.

A fourth possibility that needs no mutation at all, and is worth costing before the others:
**detect and warn**. The dump already records `suppression` per component, so the pane
could refuse to start, or warn loudly, when a component that participates in a mate is
lightweight - "2 of 4 components are lightweight; this review cannot see them" - and let
the engineer resolve them in SOLIDWORKS themselves. That captures most of the value with
none of the read-only risk, and might be the right first increment.

---

## 5. Open questions for the spec

1. **Does resolving dirty the assembly?** The suppress-test ends by telling the engineer
   the document is modified in memory and must be closed without saving. If resolving marks
   the assembly modified, this feature needs the same warning and the same discipline, and
   that changes how it should be presented.
2. **Restore afterwards, or leave resolved?** Leaving it resolved matches what the engineer
   asked for and is probably what they want next. Restoring is more conservative. It should
   be stated, not left to chance.
3. **Does the package record that a component was resolved *by us*?** It should: a review
   whose evidence exists because the tool changed the session state is a different artifact
   from one that read the session as found, and the session record should say which.
4. **Children.** Resolving a subassembly resolves what is under it. Does the table list
   leaves, top-level components, or a tree?
5. **Timeouts.** A large resolve can take minutes. What does the pane show, and can it be
   cancelled?
6. **Does this belong to feature 006's `FR-005`?** The Standards checks explicitly treat a
   lightweight instance as "not part of the assembly being graded". If components can now be
   resolved on request, that rule's wording and its tests may need revisiting.

---

## 6. Suggested acceptance

- With both pins lightweight, the pane states plainly, before any tokens are spent, that
  two components will not be examined.
- The engineer resolves both from the table, the review runs, and the interference findings
  that 2026-09-18 produced come back.
- The session record distinguishes "resolved as found" from "resolved at the engineer's
  request", and names every component that could not be resolved.
- `ReadOnlyGuard`'s denylist is unchanged; the new capability arrives as its own gate with
  its own recorded log, and no other path can reach `SetSuppression2`.
