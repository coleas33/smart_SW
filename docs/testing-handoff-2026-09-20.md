# Testing handoff — pre-test readiness

Test branch: `codex/pretest-readiness-2026-09-20`. This includes the original September 20
handoff fixes and the additional pre-test batch. Use the branch's published commit as the
build under test and record `git rev-parse HEAD` before starting.

Local release checks passed: 6,829 Python tests, 1,843 extractor tests, 1,288 add-in
tests, Python lint, and the artifact audit for the CI sentinel credential. Four Python
tests were skipped and six live tests were deselected. These are development checks;
the workstation scenarios below still need to be run.

## Install the testing build

Follow [the workstation runbook](workstation-runbook.md) for machine settings and health
checks. Close SOLIDWORKS before rebuilding or registering. Fetch the testing branch and
merge it into the workstation's existing `local` lane, then run
`extractor/tools/update-workstation.ps1 -NoPull`. Do not use an update that pulls only
`origin/main`: these changes are on the testing branch. Preserve machine settings and the
real standards profile outside Git.

## First live checks

1. At about 300 px pane width, run Review with unresolved/lightweight components. Confirm
   preparation names the unread instances, Check again refreshes them, Cancel starts no
   review, and Review available evidence preserves the complete Not-examined warning.
2. Resolve the components manually and recheck. Confirm the fresh extraction reflects the
   changed state and that changing document/configuration invalidates an old preparation.
3. Confirm the configured real standards profile is used. An unreadable configured profile
   must be a visible coverage gap, including with the procedural gate disabled.
4. Confirm matching explanations appear in Start here, finding Details, and the report.
   Follow-ups with unchanged findings should reuse them; Stop must prevent late prose
   from being attached to a stopped review. Record token usage and elapsed time.
5. Confirm Remodel explains an unavailable bridge before planning/execution. The runner
   also refuses failed/unready plans or uncalibrated stage-1 tolerances before judgement
   and applying changes. Run the existing throwaway-part probe procedure separately;
   the new checks do not enable execution or claim calibration.

## Efficiency experiment

The pane defaults remain unchanged. Compact queries are an opt-in CLI experiment:

```powershell
swreview review <package-dir> --out <new-run-dir> --explain-findings --lever compact_queries
```

For a benchmark comparison, use the same set, provider, model, effort, code commit, and
presentation mode in every run. For each repetition 1 through 3, run the off arm and then
the on arm into separate new directories:

```powershell
swreview benchmark run --set <set.json> --out <off-rep-dir> --study compact_queries --arm off --rep <n> --explain-findings
swreview benchmark run --set <set.json> --out <on-rep-dir> --study compact_queries --arm on --rep <n> --explain-findings --lever compact_queries
swreview benchmark score <run-dir> --answer-keys <answer-key-dir>
```

Score every run and use `swreview benchmark compare` on the six directories. The known
parallel-tool study can use the same sequence with `parallel_tool_calls` as the lever.
Do not combine the two experiments into one adoption claim. A held-out real design and
engineer-checked answer key are still required; the imported dumps all describe one
assembly. The answer key is used by scoring, never by the reviewer. These commands call
the configured provider and are instructions for the testing seat, not runs performed
during implementation.

## Collect a result

```powershell
swreview handoff <run-dir> --out <new-handoff.zip>
```

For a known bridge secret in the current shell, add `--bridge-secret-env <variable-name>`.
The ZIP includes available core artifacts, known optional logs, and a manifest of hashes,
settings, coverage, usage, missing files, exclusions, and redactions. Missing artifacts
remain visible; the exporter does not invent a complete run. It never overwrites an archive.

The manifest distinguishes the checkout at export time from recorded run provenance;
export-time identity alone is not proof of which build created an older run. Design names
and paths remain in local evidence. Machine settings and native CAD files are excluded;
known credentials are masked, with the detector's limits recorded. Inspect the packet
before sharing it. Keep ZIPs and real-design runs out of Git.

Send the packet with the observed result, pane width, component load state, and any failed
step. No live CAD probes or paid model reviews were performed by the implementation batch.
