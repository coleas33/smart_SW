# Quickstart: Validating Checks-First Review and the Token Budget

**Feature**: `008-checks-first-review` | **Plan**: [plan.md](plan.md) | **Contracts**: [contracts/](contracts/)

Scenarios 0 to 10 run **offline** on the development machine, with no SOLIDWORKS licence and no
key; Scenario 3 also needs the recorded dumps, which live on this machine only. Scenarios 11 to 15
are marked **[W]** and need the next workstation sitting: a licensed seat, the real standards
profile and a provider key.

## Prerequisites

Everything from features 001 to 007. Offline: the three committed replay fixtures under
`reviewer/tests/fixtures/replay/` (shaped like the recorded 830-02342 run and the two 810-11249
runs, fictional throughout), `config/standards.example.yaml` (the profile the pilot ran), the
scripted review bridge in `tests/support/review_bridge.py` and the pre-run fixture package in
`tests/support/prerun.py`.

```powershell
cd reviewer
$runs = "$env:TEMP\swreview-008-quickstart"
Remove-Item -Recurse -Force $runs -ErrorAction Ignore
New-Item -ItemType Directory $runs | Out-Null
$fx = "tests/fixtures/replay"
```

## Scenario 0 (Setup): the tokenizer, and what must not move

```powershell
uv run pytest tests/unit/test_tokens.py tests/unit/test_tool_result_text.py tests/unit/test_fake_rounds.py -q
uv run pytest tests/unit/test_report_tokens.py tests/unit/test_report_start_here.py tests/unit/test_efficiency_settings.py tests/unit/test_no_lever_in_pane_settings.py tests/unit/test_docstring_split.py tests/unit/test_prefix_stability.py -q
```

Expected: the encoding loads with the network patched off and names `o200k_base`; the adapter's
bytes are unchanged by `tool_result_text`; both report goldens are byte-identical; thirteen levers
(lever 13 since the Phase 9 amendment), none in the pane schema; the docstring and prefix pins unedited.

## Scenario 1 (US1): replay a fixture as recorded

```powershell
uv run swreview benchmark replay "$fx/big-assembly" --no-pane-defaults --standards-profile ../config/standards.example.yaml
uv run swreview benchmark replay "$fx/big-assembly" --no-pane-defaults --standards-profile ../config/standards.example.yaml --json > "$runs/big-off.json"
```

Expected: one line per round with the recorded, as-recorded and requested input; every
as-recorded figure within 1% of the recorded one; four estimated rounds (`bridge_interference`,
and since feature 010 the three touching groups judged after it) and one carried presentation
round; a recorded total of about 12.4M; `tokens counted with o200k_base`; the finding set exact -
99 recorded, 96 replayed and 3 reclassified as contacts; exit 0. The JSON validates against `ReplayReport`. The fixture
folder's files are unchanged (`Get-FileHash` before and after).

## Scenario 2 (US1): what the replay refuses

```powershell
New-Item -ItemType Directory "$runs/empty" | Out-Null
uv run swreview benchmark replay "$runs/empty"
Copy-Item -Recurse tests/fixtures/attention/check-folder "$runs/check"
uv run swreview benchmark replay "$runs/check"
```

Expected: each exits 1 with one sentence naming what is missing - no `session.json`; no
`events.jsonl` (a check folder has no provider rounds to replay).

## Scenario 3 (US1, dumps): the real recordings

```powershell
uv run pytest tests/integration/test_replay_recorded_runs.py -q
```

Expected on the development machine: every round of the three recorded reviews within 1% (at
most about 0.03%); on 830, 88 findings replayed and 11 not replayable offline (six interference,
five standards without a profile). Skipped with a reason anywhere the dumps are absent.

## Scenario 4 (US2): checks first on the fixtures

```powershell
uv run swreview benchmark replay "$fx/big-assembly" --no-pane-defaults --lever prerun_checks --standards-profile ../config/standards.example.yaml
uv run pytest tests/unit/test_prerun_digest.py tests/unit/test_prerun_repeat_guard.py tests/unit/test_attention_family_fold.py tests/unit/test_report_family_fold.py -q
```

Expected: no recorded finding lost; the requested total far below the as-recorded one; the
recorded RMS and assembly calls classed `answered from checks`; every one of the 113 groups judged,
one interference finding or (since feature 010) one contact each, with 3 recorded findings
reclassified as contacts; 62 findings added by feature 010's checks in the pre-run; the opening message carries the family counts line and no RMS id; a
repeated check answers `already_run` with no new finding; the report holds one collapsed
"Modelling practice: 85 findings across 7 rules" subsection and the ranking one family row.

## Scenario 5 (US2): live interference with a scripted bridge

```powershell
uv run pytest tests/unit/test_checks_first_interference.py tests/unit/test_ir_loader_append.py -q
uv run pytest -m perf tests/perf/test_prerun_perf.py -q
```

Expected: the live call is step 0 with the recorded settings; every group judged before the first
provider round; the rows and gaps in `package.json`, and a Retry in the same folder does not grow
them; a command-line-shaped run leaves the input folder untouched; a failed call, a failed write,
a collision, no bridge and a part root each produce their coverage row and digest line and the
review still starts; 1,000 groups judged within the perf budget.

## Scenario 6 (US3): the model's view and pruning

```powershell
uv run swreview benchmark replay "$fx/big-assembly" --standards-profile ../config/standards.example.yaml
uv run swreview benchmark replay "$fx/big-assembly" --prune-after 1 --standards-profile ../config/standards.example.yaml
uv run pytest tests/unit/test_model_view.py tests/unit/test_result_pruning.py tests/unit/test_openai_model_view.py tests/unit/test_gemini_model_view.py tests/unit/test_runner_model_view.py -q
```

Expected: with the pane defaults (the replay's default), the requested total is under 1,000,000
input tokens with no finding lost (SC-002); both prune ages are printed for the owner; no package
persist reference appears in any view; stubs are deterministic and never replace the opening
digest or the engineer's text; the session, package, report and ranking are byte-identical with
the view on and off (SC-007).

## Scenario 7 (US3): every result is in the run folder

```powershell
Copy-Item -Recurse tests/golden/fixtures/bracket-assy-interference "$runs/pkg"
uv run swreview review "$runs/pkg" --out "$runs/cli" --provider fake --pane-defaults
Get-ChildItem "$runs/cli/tool-results"
uv run swreview review "$runs/pkg" --out "$runs/cli-off" --provider fake --prune-after 1
```

Expected: the first run records `pane_defaults(fake)` on `session.json` and writes one
`step-<n>.json` per recorded step, each holding the full payload; the second exits 2 naming
`--prune-after` and `--history-pruning` (pruning is not on). A plain `swreview review` records
every change off.

## Scenario 8 (US4): one turn for a question or an answer

```powershell
uv run swreview benchmark replay "$fx/small-assembly-a" --lever parallel_tool_calls --standards-profile ../config/standards.example.yaml
uv run swreview benchmark replay "$fx/small-assembly-b" --lever parallel_tool_calls --standards-profile ../config/standards.example.yaml
uv run pytest tests/unit/test_parallel_tool_calls.py tests/unit/test_runner_provider.py -k "batch or parallel" -q
```

Expected: each small fixture's regrouped estimate under 300,000 with its assumption printed, and
its strict figure below the recorded total (SC-003 as amended). `--lever parallel_tool_calls` asks
for the OpenAI pane: the fixtures record the scripted provider, whose pane makes no parallel calls,
so without it only rule R applies and the estimates are about 381,000 and 388,000; the big fixture's follow-up round
under 30,000 (Scenario 6's output, turn 1, SC-004); three answers in one submission give three
answered records and one resumed turn, and one bad id changes nothing (SC-005); three bridge calls
in one response reach the bridge one at a time.

## Scenario 9 (US5): the cost, honestly

```powershell
uv run pytest tests/unit/test_step_sizes.py tests/unit/test_report_tokens.py tests/unit/test_honest_cost.py -q
cd ..\extractor
dotnet test SwReview.sln -c Release --filter "FullyQualifiedName~ReviewPageUsageLine" --nologo
cd ..\reviewer
```

Expected: every step carries `result_bytes` and `result_tokens`; the report keeps its cached and
uncached lines, adds "Cache split not reported" only when the provider sent no cached count, and
lists the five largest results; the pane line reads `<U> uncached + <C> cached input` or
`(cache split not reported)`, with no percentage.

## Scenario 10: the fixtures carry nothing real

```powershell
uv run pytest tests/unit/test_replay_fixture_hygiene.py tests/unit/test_standards_no_company_values.py -q
```

Expected: every path under the fictional root, no recorded design id, no email, URL or copyright
sign; the owner's denylist checked when it is on this machine; the census of populated standards
profiles still exactly the four documented files.

## Scenario 11 [W]: the real standards profile first

Place the real `standards.yaml` on the seat by hand, set `StandardsProfilePath`, and start a pane
review of any assembly: `check_standards` runs in the pre-run and its findings are in the session.

## Scenario 12 [W]: the big assembly, paid

A pane review of 830-02342 with the defaults. Record the input tokens (at most 1.5 times the
replay's requested estimate for `big-assembly`), the findings (at least the recorded 99 by
subject), every detected interference group judged, the rows in the run folder's `package.json`,
and the usage line and report both showing uncached and cached input.

## Scenario 13 [W]: the small assembly, paid

A pane review of 810-11249 with the defaults: at most 1.5 times the replay's estimate and at most
0.3M input tokens; at least the recorded findings.

## Scenario 14 [W]: Retry and the setup latency

On Scenario 12's run folder press Retry: the rows and gaps in `package.json` do not grow and the
same groups are judged. Record the `POST /sessions` duration and the seconds from `session.started`
to the first `text.delta`.

## Scenario 15 [W]: the sitting, replayed

Copy the sitting's run folders back (outside the repository) and replay each on the development
machine: every round within 1%, every unreproducible call `stored` rather than estimated. Record the
paid figures beside the replay's.

## Regression gate

```powershell
cd reviewer; uv run pytest -q; uv run pytest -q -m perf tests/perf; uv run ruff check src tests
cd ..\extractor; dotnet build SwReview.sln -c Release; dotnet test SwReview.sln -c Release
```
