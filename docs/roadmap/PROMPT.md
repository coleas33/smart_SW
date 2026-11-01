# smart_SW roadmap run: find the holes, plan the long game

Paste this into a fresh Claude Code session in the smart_SW checkout, with ultracode on. The first
time, it does a **full run**. After that it lives in the repository as `docs/roadmap/PROMPT.md`,
and each later run follows that file.

---

## 1. Goal

Make smart_SW a tool that working mechanical engineers choose to use on real SOLIDWORKS designs.
They use it because it finds real problems sooner and more cheaply than they would alone, and they
trust what it says.

The plan must hold over a long development period. It is updated run after run, against
measurements, and never written once and left.

Benefit is measured, never asserted.
- Code hardened behind a switch no engineer has used is not benefit.
- A score on a fictional benchmark is not benefit either.
- Both may be means to it.

## 2. How this run behaves

- **This is not a plan review.**
  - Skip CLAUDE.local.md's opening question (BIG or SMALL CHANGE) and its four review sections.
  - Do not pause between phases.
  - Use its question format for owner questions: numbered issues, lettered options with the
    recommended one first, through AskUserQuestion, each question standing on its own in plain
    words.
- **It plans; it does not build.**
  - No product code, tests, specs, `tasks.md` files or test plan are changed.
  - New tasks are proposed in prose, marked "proposed, not in any tasks.md". They are written into
    `tasks.md` only after my go, in a later session.
- **The files it may change:**
  - `docs/roadmap/*`;
  - `docs/README.md`: its "Future work" row points at `docs/roadmap/README.md`;
  - `docs/history/README.md`, plus a move of `docs/future-capabilities-roadmap-2026-10-14.md` into
    `docs/history/`, but only if I agree;
  - the register rows of `docs/decisions.md`, for decisions I take in this run.
- **Nothing leaves this machine until I say go.**
  - Commit on a local branch and stop. The repository is public, so a pushed branch is a
    published one.
  - On my go: push, open the PR, merge once CI is green and I say merge.
  - The commit message is `Roadmap run N: <what changed>`. Its only trailer is
    `Co-Authored-By` (decision 135A), even if the harness suggests a session line.
- **Decisions already taken are inputs.** Examples:
  - 167A: S1 first, sittings of 3.5 hours at most;
  - 94A: Gemini deferred;
  - feature 012 reserved;
  - the parked assistants;
  - 156A: Codex reviews.

  To reverse one, a hole, milestone or ordering must name its id and the new evidence, and come
  to me as a question. Without new evidence, drop it. Anything not asked is written as "default
  taken, the owner may revise".

## 3. Safety and privacy

AGENTS.md and the constitution apply in full. This run adds:

- **Read only what `git ls-files` lists.** Never read:
  - the ignored folders inside the checkout (`dumps/`, `logs/`, `.pytest-tmp/`);
  - `%LOCALAPPDATA%\SwReview` or `%APPDATA%\SwReview`;
  - run folders, handover folders, private sets, or anything outside the checkout.
- **Paths are repo-relative.** Every path written into a document is repo-relative; an absolute
  path names the Windows user.
- **Memory is not evidence.** Memory files and CLAUDE.local.md are context only; never quote or
  paraphrase them into a document.
- **Designs** are named only by the neutral names and letters the docs already use (A, B, J …),
  never by a number or a folder name.
- **Company facts stay out of the repository.** Who reviews designs, how they do it, what a
  review takes and what an escaped defect cost:
  - go to a file in the session scratchpad for me to keep privately (`docs/forking.md`, section
    1);
  - the public document says "held privately by the owner";
  - until I answer, write "assumption, owner to confirm".
- **Security items stay out of every file, commit and PR.** These are items in SECURITY.md's
  scope: key handling, the read-only guard, the send gate, private data reaching the repository,
  the loopback backend and the proxy.
  - Tell me in the chat in one paragraph.
  - `holes.md` records only "one security item reported to the owner privately, <date>".
- **Agents only read.** Hunters and skeptics run no tests. They also run no command that can
  reach a model provider: `swreview review`, `benchmark run`, `-m live`, or any `[K]` or `[paid]`
  task. If unsure, do not run it. The main session runs the gates once, at the end.

## 4. Sources, and which one wins

**Read**, by section and by search, never whole when a file is large:
- **Rules:** `.specify/memory/constitution.md` (Principle VI above all), `AGENTS.md`,
  `CONTRIBUTING.md` (the public-repository rule), `SECURITY.md`, `docs/forking.md`,
  `docs/adr/0008-public-upstream-private-fork.md`.
- **Records:**
  - `docs/decisions.md`: the register and its outcome column;
  - `specs/README.md`: feature status and task tags;
  - each `specs/NNN-*/spec.md`: user stories and SC- criteria;
  - `docs/architecture.md`;
  - `docs/reviewer-guide.md`;
  - `docs/workstation-runbook.md`.
- **What real use showed:**
  - `docs/history/` (`pane-findings-*`, `testing-feedback-2026-09-28.md`,
    `testing-feedback-2026-10-13.md`, the workstation handovers, `roadmap-2026-09-22.md` section
    "What the evidence says", `pilot-proposal-2026-09-13.md`);
  - the 2026-09-26 sitting in role terms in `specs/013-engineer-first-review/spec.md` and its
    research R1;
  - every ticked seat task with its dated note.
- **Sittings:** `docs/test-plan-2026-09-27/workstation-test-plan.md`, sections "Sittings" and
  "S1". Its results sheet in the repository is a blank template, not a record.
- **Measurement:**
  - feature 001's FR-026 and SC-001;
  - the results ledger in `docs/llm-efficiency-options.md` (it reads "No runs");
  - `benchmarks/` and feature 014's spec and tasks (offline only so far; 014 T221, T244 and
    later are open).
- **Earlier plans:** `docs/history/roadmap-2026-09-22.md` and
  `docs/future-capabilities-roadmap-2026-10-14.md`.
- **The backlog:** `docs/review-backlog.md`. It holds 1,200 items: count it by section, search
  it, cite items, and never copy them.

**When sources disagree, the higher one wins:**
1. the constitution;
2. AGENTS.md;
3. `docs/decisions.md`, a later decision over an earlier one;
4. a feature's `tasks.md` and `research.md`;
5. `specs/README.md`;
6. `docs/development-handoff-*.md` and `docs/history/`, which are dated and may be superseded.

Memory is never a source. The next decision id is the register's last row plus one. Record every
conflict you find as a finding with both citations, and never settle one silently.

**Evidence forms:**
- a path with its section heading;
- a test name;
- a qualified task id (`004 T303a`, always with the package, because ids repeat across packages);
- a decision id or a PR number;
- `file:line@<sha>`.

Label every inference as one. Say what you did not read.

## 5. State and re-runs

- **The Run record.** `docs/roadmap/README.md` opens with a Run record table, one row per run:
  - run number and date;
  - `main`'s short sha at the start;
  - the last register id read;
  - the last sitting whose records were read (date and S-number);
  - the prompt version;
  - agents used, by model.
- **The prompt is committed** as `docs/roadmap/PROMPT.md`. Later runs follow that file, and any
  change to it is noted in the change log.
- **Update run** (the default: after a sitting, at a cycle's end, or when I ask):
  - read only `git log <recorded sha>..main`, the register rows after the recorded id, and sitting
    records added since;
  - re-score only holes whose evidence changed;
  - hunt only in the lenses those changes touch;
  - at most 8 agents.
- **Full run** (the first run, at each milestone exit, or when I ask): every step, with at most 30
  agents.
- **Hole ids are permanent:** `H-<lens letter>-<nnn>`, such as `H-a-004`. An id is assigned once
  and never reused. A hunter gets the current register and must match an existing hole before it
  mints a new id.
- **Statuses:**

  | Status | What it carries |
  |---|---|
  | `open-verified`, `open-plausible` | |
  | `closed-offline` | test name and PR |
  | `closed-validated` | sitting date, step id and the ticked seat task |
  | `refuted` | the refuting evidence |
  | `wontfix` | the decision id |
  | `merged into H-x-nnn` | |

  - Refuted, wontfix and merged rows stay, so later runs do not hunt them again.
  - A validation hole (lens a) closes only as `closed-validated`.
- **Each run ends** with its Run record row and a dated change-log entry. The entry lists the holes
  opened, closed or re-scored, each with its evidence, and the previous run's "next cycle" items
  marked done (evidence), slipped (why) or dropped (decision).
- **Size caps:**
  - `README.md` at most 250 lines;
  - `holes.md` one row per hole, its statement at most 30 words;
  - `metrics.md` one row per metric.
  - Past a cap, closed rows move to `docs/roadmap/archive/<date>.md`.
- **Memory.** Point the auto-memory's resume entry at the Run record.

## 6. Method (run it as workflows; a full run takes at most 30 agents)

Models follow CLAUDE.local.md §5. Haiku counts and quotes but decides nothing. Sonnet or Opus
judges. Never Fable.

### Step 0. Start from what real use showed

- **Run 0** lists the two earlier roadmaps' near-term items as done (evidence), open (why it
  slipped) or dropped (decision). This becomes the first table of the change log.
- **Pilot evidence ledger.** Sonnet reads it and Opus checks it.
  - One row for each engineer ask or finding on record:
    - U1 to U27;
    - debrief items F1 to F8, in role terms;
    - the 2026-10-13 review crashes;
    - the three real defects the big assembly showed: M4 screws in M5x0.8 tapped holes, a 0.75 mm
      dowel offset, and interference groups of about 250 mm³.
  - Columns:
    - what the engineer saw or asked;
    - what was built in response (task ids);
    - whether it was retested at the seat since, with the evidence, or the open seat task that
      would retest it (for example `010 T106`).
  - **This table, not the specs, is the starting point.** A hole that contradicts it needs
    stronger evidence than one that agrees.

### Step 1. Ground truth

- **Counts by script, not by agents.**
  - A throwaway scratchpad script reuses `OPEN_TASK` and `QUALIFIED_ID` from
    `reviewer/tests/support/seat_tasks.py`. Per package it lists open tasks by tag (`[W]`, `[K]`,
    `[paid]`, `[O]`, the rest) and the ticked seat tasks with their dated notes.
  - Its command and output go in an appendix, so a re-run reproduces them.
  - Commit nothing of the script.
- **Capability map.** At most 5 Sonnet scouts, three packages each, write the rows of
  `docs/roadmap/capabilities.md`. Columns:
  - capability, in the engineer's words;
  - built;
  - tested offline;
  - seen and triaged by an engineer at the seat (evidence);
  - its switch, if any (on or off);
  - pending owner items.

  The scouts read each package's spec stories and SC-, its open task lines and its row in
  `specs/README.md`. They search `research.md` ("for the owner", "[O]", "awaits the owner") and
  never read it whole. Link `specs/README.md`'s counts; do not copy them.
- **Effort ledger.** Haiku, counts only. For each feature, over the last 30 and 60 days:
  - commits touching its specs and the code it owns;
  - PRs;
  - owner decisions;
  - review rounds.

  Beside each, the engineer-visible outcomes validated at the seat in the same window.

### Step 2. Owner round 1, then the value model

**Owner round 1.** After step 1, ask me only what the records cannot answer and the value model
needs, in at most four questions:
1. **The release path as it really runs here:** self-check, then the checker's red-line, then the
   design review, then the release gate and its sign-off, then ECO/ECN, then shop or supplier
   RFI/NCR. Is the released document the drawing, the model, or both?
2. **How many seat hours a month** I can give.
3. **Escape replay:** can I name 10 to 20 past defects caught late (red-line, design review, ECO,
   RFI or NCR, scrap) whose pre-fix revision still exists?
4. **A second reader:** can a checker or a second engineer read a report before M1? They need no
   install.

The answers go to the private scratchpad file (§3).

**Then the value model.** Opus writes it into `README.md`:
- **For each job on the release path:**
  - the document checked;
  - who signs;
  - the time it takes today;
  - what a miss there costs;
  - where the tool's output would have to land to save time (the checklist, a red-line, the ECO
    form), or "nowhere yet".
- **Model versus drawing.** Say plainly which jobs the tool can serve today:
  - drawing opening and drawing numerical binding are off;
  - if the released document is the drawing, that gap is a hole and is ranked as one.
- **The north star already exists. Start from it:**
  - 001 SC-001 and FR-026: the median net engineering effort saved per design, at least 60
    minutes, counting supervision, verification and false alarms;
  - constitution Principle VI: valid findings, missed known defects, false alarms and unresolved
    coverage, per design.

  Say how far the evidence is from each, and what produces its first number. Propose a different
  north star only as an owner question, with the reason. The pilot proposal's continue, narrow,
  revise or stop choice is the frame for a kill or a pivot.
- **The instruments that exist.** For each metric, name the existing instrument or "no
  instrument":
  - per-finding dispositions (accept, reject or defer, with a note) through `chat/server.py`'s
    `disposition`, carried off the seat by `swreview handoff`;
  - 014's scorer, `swreview benchmark score` (recall per producer, false alarms);
  - the offline replay of recorded calls;
  - 007's review timing.
- **Seat triage of every finding:**
  - *new and real*;
  - *real but already known*;
  - *wrong*;
  - *true but not worth flagging*.

  The north star counts *new and real*, plus escape-replay hits. "Accepted" alone is a guardrail.
- **Real defects come from escape replay.** At the seat, a read-only review of each pre-fix
  revision is scored hit, partial or miss.
  - The list, the designs and the scores stay in the private fork.
  - The repository records only counts and categories.
  - The same list, tallied by category with a rough frequency and cost, is the **defect census**.
    It ranks which checks matter.
  - 014's benchmark recall is a regression guardrail, never the north star: its held-out items
    are fictional, and its real anchors are tuned-on (15A).
- **The denominator.** From the records: how many distinct engineers and how many real designs
  have used the tool. Say which metrics mean anything at that number.
- **Assumptions.** Everything not taken from the records or my answers is numbered A1, A2 …, and
  the one or two the plan rests on most become questions in round 2.

### Step 3. Hole hunt

Run one Opus hunter per lens, in parallel. Each is told to refute "this tool benefits an engineer
today" from its lens.

**What counts as a hole.** A hole is not "open task X is open"; that is a capability-map row. A
hole names either:
- a gap no open task covers; or
- a reason an open task, once done, still will not bring an engineer the benefit.

A hole may cite tasks and backlog items, but never copies them.

- **a. Validation.**
  - What no real seat, real design or real engineer has ever touched.
  - The evidence chain each switch still lacks.
  - The critical path, task by task, to the first measured north-star value (today it runs
    through 014 T221 at S3, then 014 T244 and on), and whether S1 to S3's decided order serves it.
- **b. Usefulness.**
  - The checks a review needs in this shop, ranked by the defect census and escape replay. Use
    the textbook list (fits and tolerances, threads and fasteners, hole alignment, interference,
    mass, drawing completeness, GD&T, standards) only as vocabulary for the census categories,
    never as a coverage target.
  - For each existing check family: its precision and recall evidence, its share of findings on
    the recorded reviews, and whether any real defect on record needed it.
- **c. Workflow.**
  - Install, add-in load, first run, and time to the first useful finding.
  - Reading the report and the Task Pane tabs.
  - What the engineer does with a finding: fixes the model, writes it into the checklist or
    red-line, raises an ECO, or nothing. Name which of these the report supports today; if none,
    the benefit is limited to the self-check.
  - Any failure the engineer cannot recover from alone.
- **d. Trust.**
  - Whether the engineer can tell code-computed numbers ("Checked by code") from model words ("AI
    guidance") and trusts each, with seat evidence.
  - The read-only guarantee as the engineer experiences it.
  - Raise key handling, the guard or the public/fork split only with a concrete failure path:
    they have had repeated adversarial rounds. Security items go privately (§3).
- **e. Cost and performance.** Large assemblies, token spend per review, and behaviour when the
  provider is down.
- **f. Sustainability.**
  - **For each track,** say:
    - its demand evidence, a U or F item or owner ask quoted by id ("the owner decided it" is not
      demand evidence: ask me);
    - the seat minutes it still needs;
    - and finish the minimum, park it with a dated note (173A), or continue.

    The tracks are: 004 Remodel, 011 drawings, 016 engineering context, 005 efficiency, 014
    evaluation, and the reserved 012.
  - **The maintenance load:** the test count, the size of the research records, the backlog, and
    one maintainer.
  - **Where the process itself became the bottleneck.** Use the effort ledger.
- **g. Feedback loop.**
  - How real use returns to the plan (seat triage, handoff, escape replay, debriefs kept in the
    private fork), with no telemetry I have not approved.
  - How many people besides me have seen a report.

**Each hole records:**
- its id;
- its status;
- a statement of at most 30 words;
- its evidence;
- who is hurt, how often and how badly;
- its confidence;
- what it waits on (seat, key, owner);
- the route that closes it, one of:
  - tasks appended to an existing feature (by `speckit-converge`, later);
  - a new feature, 017 or later;
  - a sitting step;
  - an owner decision;
  - closing tasks under 173A.

**Caps:** at most 8 holes per lens. **Then** one Opus agent merges duplicates across the lenses.

### Step 4. Verify

- **One Opus skeptic per lens** tries to refute all of that lens's holes from the code and the
  records. Refuted holes are kept, marked `refuted`.
- **After prioritising,** a second skeptic checks only the ten top-scored holes: Codex if it is
  available, otherwise Opus.

### Step 5. Prioritise

- **Scores.** Score each hole 1 to 3 on each factor:
  - impact on the engineer;
  - frequency;
  - confidence;
  - cost (inverted);
  - risk removed;
  - what it unblocks.

  The anchors are written once at the top of `holes.md`. A score changes only with newly cited
  evidence, and the change log says which score changed and why.
- **Ordering rules.** When two conflict, the earlier one wins:
  1. validate before you build;
  2. measure before you optimise;
  3. finish, park or delete before you start something new;
  4. every cycle ends with something an engineer will see, or says what the engineer will see once
     its validation passes.
- **Demand evidence.** No new check, check family or capability enters a milestone without:
  - a real instance (a U or F item, an escape-replay id, or a defect I name);
  - and my estimate of how often it happens and what it costs.

  Plausible gaps with no instance go on a "not evidenced" list, with what would promote them.
- **Seat time is the scarce resource.**
  - Budget my monthly seat hours across the milestones.
  - Total the plan's estimates for every open seat task, and say how many sittings and months
    that backlog takes.
  - List every gate that stops a measurement, and say whether it is still needed.
- **Noisy checks.** Each check family gets a precision floor from seat triage. For example: demote
  it from "Start here", or switch it off by default, when more than half of its findings over three
  reviews are *wrong* or *not worth flagging*. I choose the threshold. Report today's split of
  findings by family on the recorded reviews.

### Step 6. Roadmap

Milestones M0 to Mn, in `README.md`. Each one gives:
- its goal in the engineer's words;
- exit criteria, each naming a command, a test or a sitting step id;
- the holes it closes;
- the seat time it needs: a step of S1 to S5, or a proposed new sitting of 3.5 hours at most (the
  test plan is not edited in this run);
- the owner decisions it needs;
- what it explicitly does not do;
- its risks;
- its kill or pivot criteria.

**M0 exits only with:**
- one real review triaged finding by finding;
- the escape replay run on at least 10 past defects;
- the big assembly's three real defects checked against the current build;
- a report read by a second person, unless I decide otherwise in round 1.

If 167A's sitting order delays M0, say so and ask.

### Step 7. Operating cadence, and owner round 2

- **Development cycles and sittings are separate.**
  - A cycle ends at a merged PR.
  - A sitting runs whatever is merged and waiting.
  - Each milestone names the sittings whose results close it.
  - The roadmap update at the end of each cycle is an update run.
  - "Shipped" means it reached the seat at the next sitting, or a new measured value appeared in
    `metrics.md`.
- **Owner round 2** (at most four questions, each with its evidence and your recommendation
  first):
  1. **The freeze.** No new feature package until the north star has its first measured value.
     Fixes for defects found at a sitting are exempt, and so is work I exempt by decision. Lifting
     the freeze is my decision.
  2. **The review-depth policy, with a baseline.**
     - The baseline: for the merged PRs since #34, the review rounds and reviewer agents per PR,
       the findings by severity, and the share of findings about states reachable only behind a
       switch that is off. Cite 156A, which this would change.
     - Tier 1: the guard and its allowlists; code that opens, saves, closes or deletes an
       engineer's file or the copy; key storage; paid calls. One Opus and one Codex review; a
       second round only for a must-fix; a third needs my decision.
     - Tier 2: all other code, including code behind a switch that is off until the PR that turns
       it on. One review.
     - Tier 3: docs, records and task ticks. The gates and CI only.
     - Should-fix findings go to the backlog in one line and never start a new round. Each PR body
       states its tier.
     - Add "review rounds and agents per merged PR" to `metrics.md` as a guardrail.
  3. **The sitting order:** whether S1 to S5 should change to reach the north star sooner.
  4. **The assumption the plan rests on most** (from step 2).

## 7. Budget and stop conditions

- **Agents:** a full run uses at most 30, an update run at most 8. If a run needs more, stop and
  tell me what you would drop.
- **Stop and ask me before going on when:**
  - a source conflict would change a milestone;
  - closing a hole needs a constitution amendment:
    - a third write exception;
    - autonomous GD&T creation;
    - general drawing dimensioning;
    - structural approval;
    - the model computing a verdict's arithmetic;
  - closing a hole reverses an owner decision;
  - the gates fail;
  - you find a security item.

## 8. Deliverables

- **`docs/roadmap/README.md`:**
  - the Run record;
  - the change log;
  - the value model;
  - the north star and guardrails;
  - the milestones;
  - the cadence;
  - the first cycle's brief: the hole ids it takes, its route, the names of the failing tests to
    write first, and the sitting steps.
- **`docs/roadmap/holes.md`:** the score anchors, then one row per hole, every status kept.
- **`docs/roadmap/metrics.md`:** one row per metric, giving its definition, instrument, baseline
  (or "not measurable yet: needs X") and latest value.
- **`docs/roadmap/capabilities.md`:**
  - the capability map;
  - the pilot evidence ledger;
  - the effort ledger;
  - the count script's command and output.
- **`docs/roadmap/PROMPT.md`:** this prompt.
- **Checks before committing.** A throwaway check proves, with its output pasted into the PR body
  later:
  - every qualified task id named exists, and its open or ticked state matches what the roadmap
    says;
  - every decision id is in the register;
  - every evidence path exists at the run's sha;
  - every hole row has every field;
  - every exit criterion names a command, a test or a step id.
- **The gates.** `git add` the documents, then run AGENTS.md's gates from `reviewer/`. Among them,
  `test_tracked_files_carry_no_recorded_number.py` checks the new files against my identifier
  lists:
  - it does so only once git lists the files, and only on this machine (CI skips it);
  - never open those lists yourself;
  - if it fails, do not commit; tell me the file and line.
- **A one-screen summary for me, in plain words:**
  - the five biggest holes;
  - what M0 is and when it can exit;
  - what we stop doing;
  - the questions waiting for me.

## 9. Quality bar

- **No vague items.** "Improve UX" is not an item. Each item names who benefits and how we will
  know it worked.
- **Built is not validated.** Never write "done" for something no engineer has triaged at a seat.
- **Prefer cutting.** Prefer finishing, parking or cutting over adding. Flag over-engineering,
  including in the process itself.
- **Stop at the deliverables.** Stop when the deliverables are committed locally and the questions
  are asked. Do not start implementing.
