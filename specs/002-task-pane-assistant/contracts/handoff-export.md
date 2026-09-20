# Local review handoff export

`swreview handoff <run-dir> --out <archive.zip>` creates one local ZIP for an engineer to
inspect or attach manually. The command accepts exactly one review run folder and refuses
to overwrite an existing archive or place the archive inside that folder.

The archive contains `handoff-manifest.json` and an allowlist of run records:
`package.json`, `session.json`, `attention.json`, `report.md`, and `events.jsonl` when
present. It may also contain the recorded `run-provenance.json`, `check.json`,
`chat-log.jsonl`, and named extraction/check log files. Missing required records are listed
in the manifest so an incomplete run remains useful. Arbitrary recursive files, native CAD
documents, machine settings, environment files, and credentials are never discovered.

The manifest records export-time Git revision and dirty state, recorded run provenance when
present, safe session/provider/efficiency/explanation settings, coverage and usage summary,
each included artifact's byte count and SHA-256, and missing or excluded artifacts. The
package and report may retain real-design paths as engineering evidence; those paths are
references only and their native targets are not copied.

Configured secret values are redacted with the product redactor, and the known provider-key
shapes are masked in text artifacts. This is a best-effort detector and never proves that
unknown or undiscoverable secrets are absent. UTF-8 text is required for selected records;
each file is bounded, the total is bounded, and symlinked or escaping artifacts are refused.

Publication uses a temporary archive and an atomic no-overwrite link into the destination
directory. The archive remains local; export does not upload or send the run anywhere.
