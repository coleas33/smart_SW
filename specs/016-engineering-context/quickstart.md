# Offline engineering context

This delivery works with saved evidence packages on a machine without SOLIDWORKS.
It stores requirements and total applied forces, with explicit engineer confirmation.
It does not create drawings, apply Simulation loads, infer supports or certify a design.

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

Next workstation gate: selected native faces, scoped reference resolution across a new
extraction, unsaved-state attestation and engineer UI. Those require SOLIDWORKS testing
on the other machine. Automated drawing writers and structural analysis remain later
roadmap work.
