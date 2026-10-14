# Engineering context

This delivery works with saved evidence packages on a machine without SOLIDWORKS.
It stores requirements and total applied forces, with explicit engineer confirmation.
It does not create drawings, apply Simulation loads, infer supports or certify a design.

## In the Review pane

Open a saved part or assembly and expand **Engineering context**. Choose **Extract
context evidence** to save a package without starting the model review. Choose a saved
target, or use **Use selected component or face** to prefill a unique target already
present in the extraction. Selection is an uncalibrated observation: it does not verify
that current geometry still matches the saved package. A selected face missing from
the extraction remains unavailable.

Enter a requirement or total force, a stable input ID, input source and assumptions.
For a force, choose N, kN or lbf, its signed direction, saved root/component coordinate
frame and optional point in metres. Leave an unknown magnitude blank and give a reason.
Save the draft, inspect the displayed target, values, frame and source, then enter your
name and confirm the exact displayed input. To change an existing input, choose its
**Edit saved input** button, make the changes and choose **Save revised input**. This
creates a new revision and invalidates its old confirmation. Typing an existing name
in the new-input form does not replace it; **New input** starts a separate draft.

Choose **Review with saved context** to attach the displayed context revision to that
same evidence package. It does not extract again. Ordinary **Review** still starts the
existing review flow. Switching the active document/configuration or changing the saved
package requires preparation again. Unknown and draft inputs can inform a review with
their recorded states; they do not become confirmed forces.

Live checks can append evidence when the review starts. If that changes the exact
saved baseline, the model's opening summary retains the historical inputs and marks
their applicability as needing review. Confirmation is never carried to changed
evidence automatically.

Pane stores live under `run_root/.engineering-context/<run_id>`, beside the extracted
run folders. The API displays engineering values while omitting private source paths,
native reference bytes and actor history. Keep the private store when preserving local
approval history. See the [pane contract](contracts/pane-context.md) and the pending
[SOLIDWORKS workstation checks](native-entry.md).

## Command line

From `reviewer`, install with `uv sync --all-extras`. Use a private context directory
outside the extracted package and outside CAD source directories. The examples use
fictional package-local component IDs; find the actual IDs in your `package.json`.

```powershell
uv run swreview context init C:\Review\extracted --store C:\Review\private-context --json
```

Copy `head_digest` from the response. Every write requires the digest of the current
head, so an old command cannot overwrite another edit.

```powershell
uv run swreview context requirement C:\Review\extracted --store C:\Review\private-context --id req:operating-load --kind component --entity cmp:0001 --text "Support the specified operating load." --expected-head <HEAD_DIGEST> --json
uv run swreview context force C:\Review\extracted --store C:\Review\private-context --id force:operating --kind component --entity cmp:0001 --magnitude 2 --unit kN --direction "0,0,-1" --assumption "Total force; distribution not specified." --expected-head <NEW_HEAD_DIGEST> --json
uv run swreview context show C:\Review\extracted --store C:\Review\private-context --json
```

Directions and optional `--point-m "x,y,z"` use root document axes by default. Use
`--frame-component cmp:0001` for that occurrence's local axes. Only rigid right-handed
transforms are supported; a point is translated, a force vector is rotated. Unit
conversion and direction normalization run in checked code. A total force attached to
a face uses `--kind face --entity <FACE_ID> --component <OCCURRENCE_ID>`; no traction or
pressure distribution is implied. A repeated instance needs its own record/anchor.

Omit magnitude and supply `--unknown-reason "Awaiting operating load case"` to retain
an unknown force. It remains visible and cannot be confirmed as a complete force.
`--provenance ai_proposal` preserves that origin even after engineer confirmation;
`--assumption` is repeatable. These input records are separate from extracted CAD facts.

`show` is a private operator inspection: it displays the complete typed inputs,
provenance, assumptions, binding, numerical conversion and exact digests. Review those
contents before approving a record:

```powershell
uv run swreview context confirm C:\Review\extracted --store C:\Review\private-context --id force:operating --actor <ENGINEER> --expected-head <HEAD_DIGEST> --record-digest <RECORD_DIGEST> --dependency-digest <DEPENDENCY_DIGEST> --json
```

The CLI records the named actor's explicit local decision; it does not authenticate an
identity. It confirms the exact engineering input for a saved snapshot, without granting
CAD execution permission, drawing acceptance or structural acceptance. Repeating a
requirement/force command with the same ID edits it, increments its revision and leaves
the old receipt as history. Current approval then becomes `needs_review`.

A changed extraction requires a new context in a new private directory. Inspecting an
old context against a changed package reports the mismatch and retains history; it never
automatically rebinds. Baselines remain immutable within a context so restoring old
evidence cannot revive approval. `matched_snapshot` attests only the saved evidence;
live/unsaved CAD state remains `not_observed`.

Explicitly attach context to a review:

```powershell
uv run swreview review C:\Review\extracted --out C:\Review\run --engineering-context C:\Review\private-context --provider fake --json
```

`fake` exercises setup without a model or network. With a configured provider, the
opening message includes a bounded summary and two additional read-only tools:
`get_engineering_context_summary` and `get_engineering_context_record`. The run retains
the sanitized `engineering-context-summary.json` with context/revision digests. The
full private sidecar stays in its store. Tools omit native references, local paths,
provenance source labels and actor names; counts identify omitted/truncated data. Each
read re-assesses the supplied evidence. Nothing is discovered or attached automatically.

The immutable store uses `engineering-context.json` as its head, numbered files under
`revisions`, and an exclusive `.engineering-context.lock`. Busy/stale locks are never
automatically broken. A failed head replacement preserves the old published head but
can leave an unpublished revision. Preserve and inspect it: only publication of the
identical original artifact can reuse that revision; a different retry is refused.
There is no automatic recovery or revision-deletion command in this delivery.

Next workstation gate: calibrate selected native faces and repeated occurrences, then
establish source freshness and scoped reference continuity across a new extraction.
The pane and read-only adapter are implemented, with offline tests; actual SOLIDWORKS
behavior requires testing on the other machine. Automated drawing writers and structural
analysis remain later roadmap work.
