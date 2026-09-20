/*
  The Remodel page, tab 5 (T133, contracts/pane-remodel-messages.md).

  Five rules hold everywhere in this file:

  1. Markup is never assigned and no handler is inline. Every node is built through
     `shared/dom.js` (T080), which is the single place the "insert every untrusted string with
     createTextNode" rule lives. On this page nearly every string is untrusted: a feature name
     is whatever an engineer typed into the SOLIDWORKS feature tree, a rebuild reason's detail
     is assembled out of those names, and a description or a rationale was written by a
     language model that was handed a part someone else authored.
  2. Every host message is `{type, id, payload}` and replies echo `id`. An object is posted
     rather than a string so the host reads it with `WebMessageAsJson`.
  3. The page names no path. `remodel.*`, `report.open` and `folder.open` carry the `run_dir`
     the host itself issued in `remodel.planned`, and the host resolves it against its own run
     record. A page that could name a path could open anything on the workstation.
  4. The page decides nothing about the run. It does not order changes, does not roll anything
     back and issues no verdict; it shows what the host read out of the run folder. A value
     that has not been written yet is said to be missing, never rendered as a zero - a
     `grade_after` with no failures reads as a part that passed.
  5. Rendering is a function of its argument and of nothing else. `renderResult`, `renderPlan`,
     `appendChange` and `renderRun` are exported for the page tests, which call them inside the
     real page under the real CSP; the tab renders through the same functions, so a row a test
     built behaves exactly like a row the tab built.
*/

(function () {
  'use strict';

  var dom = window.SwReviewDom;
  var bridge = (window.chrome && window.chrome.webview) ? window.chrome.webview : null;

  /**
   * The eight `RunState` values of data-model.md section 11 and no others, each in its own
   * words. `remodel.result` reads `state` straight out of `plan.json`, so a ninth value means
   * the artifact is ahead of this page - it is reported as it was read rather than rounded to
   * one of the eight.
   */
  var RUN_STATES = {
    planned: 'planned: the copy exists and the plan is written. Nothing has been applied yet.',
    judging: 'judging: the model is proposing descriptions and globals into the plan.',
    applying: 'applying: changes are being written to the copy, one at a time.',
    verifying: 'verifying: the tree and the geometry are being re-read after the last change.',
    saved: 'saved: verification passed and the copy was saved.',
    truncated: 'truncated: a limit stopped the run before every planned change was applied. '
      + 'The report names how many were applied and which were not.',
    failed: 'failed: the run was abandoned and the report says why. The copy has been deleted.',
    discarded: 'discarded: you deleted the copy. Every other artifact is still in the run folder.'
  };

  /** The grade's buckets, in the order the grade states them: what to act on first. */
  var BUCKETS = ['failed', 'warned', 'checked', 'skipped', 'unresolved', 'out_of_scope'];

  /** What each bucket is called on screen. The token stays the machine-readable one. */
  var BUCKET_LABELS = {
    failed: 'failed',
    warned: 'warned',
    checked: 'checked',
    skipped: 'skipped',
    unresolved: 'unresolved',
    out_of_scope: 'out of scope'
  };

  var pending = Object.create(null);
  var nextId = 0;

  var state = {
    backend: null,
    token: null,
    runRoot: null,
    documentInfo: null,
    limits: null,
    runDirectory: null,
    result: null,
    // A missing field keeps compatibility with an older host; an explicit false means the
    // bridge has attached and deliberately has no remodel seat.
    remodelAvailable: true,
    remodelAvailabilityMessage: null,
    planning: false,
    running: false,

    /** Whether a `ready` is in flight, so a second status does not ask again on top of it. */
    initPending: false
  };

  var ui = {};

  // ---- transport: the host ----------------------------------------------------------------

  function send(type, payload) {
    var id = 'm' + (++nextId);
    var message = { type: type, id: id, payload: payload || {} };
    return new Promise(function (resolve, reject) {
      pending[id] = { resolve: resolve, reject: reject };
      if (!bridge) {
        delete pending[id];
        reject(new Error('this page is not hosted in the SwReview task pane'));
        return;
      }
      bridge.postMessage(message);
    });
  }

  function onHostMessage(event) {
    var message = event.data;
    if (!message || typeof message.type !== 'string') {
      return;
    }

    var waiting = (typeof message.id === 'string') ? pending[message.id] : null;
    if (waiting) {
      delete pending[message.id];
      if (message.type === 'error') {
        waiting.reject(asError(message.payload));
      } else {
        waiting.resolve(message.payload || {});
      }
      return;
    }

    handleUnsolicited(message);
  }

  function asError(payload) {
    var error = new Error((payload && payload.message) || 'the host reported an error');
    error.errorClass = (payload && payload.error_class) || 'HostError';
    error.retryable = !!(payload && payload.retryable);
    return error;
  }

  /**
   * The four unsolicited rows of the contract, plus a bare `error`.
   *
   * Every one of them is a thing the engineer would otherwise have to guess at: what stage the
   * run is in, how far through the plan it is, that another change has just been written, that
   * the copy went away, and that the backend stopped.
   */
  function handleUnsolicited(message) {
    var payload = message.payload || {};
    switch (message.type) {
      case 'status':
        showStatus(payload);
        return;
      case 'remodel.progress':
        showProgress(payload);
        return;
      case 'remodel.change':
        appendChange(payload);
        return;
      case 'document.changed':
        state.documentInfo = (payload && payload.path) ? payload : null;
        applyRemodelCapability(payload && payload.remodel);
        renderDocument();
        return;
      case 'backend.stopped':
        state.backend = null;
        state.token = null;
        renderBackendState('The backend stopped. Reopen the pane to start it again.', true);
        return;
      case 'error':
        showBanner(asError(message.payload).message);
        return;
      default:
        return;
    }
  }

  // ---- the run ------------------------------------------------------------------------------

  /**
   * Press Remodel: the host refuses everything it can refuse before anything is copied, then
   * copies, opens, rolls, rebuilds, dumps and plans. The page waits and shows what it is told.
   */
  function planRun() {
    if (state.planning || state.running) {
      return;
    }

    if (!state.remodelAvailable) {
      showBanner(state.remodelAvailabilityMessage
        || 'Remodel is unavailable until this build has a remodel seat.');
      return;
    }

    state.planning = true;
    hideBanner();
    setRunStatus('Reading the part...');
    renderControls();

    send('remodel.plan', {})
      .then(function (planned) {
        renderRun(planned.run_dir);
        renderPlan(planned.plan_summary);
        setRunStatus('Planned. Press Start to apply the plan to the copy.');
        return refreshResult();
      })
      .catch(function (error) {
        showBanner(error.message);
        setRunStatus('');
      })
      .then(function () {
        state.planning = false;
        renderControls();
      });
  }

  /**
   * Press Start: phases B, C and D run to completion. There is no approve-each-change mode, so
   * what the page offers while it runs is Stop, and the change list grows underneath.
   */
  function startRun() {
    if (!state.runDirectory || state.running || state.planning) {
      return;
    }

    if (!state.remodelAvailable) {
      showBanner(state.remodelAvailabilityMessage
        || 'Remodel is unavailable until this build has a remodel seat.');
      return;
    }

    state.running = true;
    hideBanner();
    setRunStatus('Running...');
    renderControls();

    send('remodel.start', { run_dir: state.runDirectory })
      .then(function () {
        // `remodel.started` is the host's acknowledgement that the run has begun, not a report
        // that it has ended: the host replies before it schedules phases B to D, precisely so
        // the message thread stays free to deliver `remodel.stop`. The page therefore stays in
        // the running state - which is what keeps Stop pressable - until a terminal `status`
        // arrives. Clearing it here would disable Stop one microtask into a run that has
        // twenty minutes left.
        return refreshResult();
      })
      .catch(function (error) {
        // The start was refused, so no run began and no terminal `status` is coming.
        showBanner(error.message);
        endRun();
      });
  }

  /**
   * The run is over: a terminal `status` (`ready` or `error`), the host's answer to a
   * `remodel.stop`, or a `remodel.start` that was refused outright. Those are the only ways out
   * of the running state, and each of them re-reads the result, because what the run left in the
   * run folder is the only thing the page reports.
   */
  function endRun() {
    if (!state.running) {
      return;
    }

    state.running = false;
    renderControls();
    refreshResult();
  }

  /**
   * Press Stop: the executor finishes the change in flight, inverts it if it failed, finalizes
   * the artifacts and reports the run as `truncated`. The page says so rather than implying the
   * run ended where the engineer pressed.
   */
  function stopRun() {
    send('remodel.stop', {})
      .then(function (stopped) {
        setRunStatus(
          'Stopping. ' + dom.scalar(stopped.changes_applied)
            + ' change(s) applied; the change in flight is finished and the artifacts are '
            + 'finalized first.');

        // The host answers this only once the executor has finalized, so the run is over by
        // the time it arrives. Normally the terminal `status` has already ended it; this is
        // the second of the two ways out, not a second ending.
        endRun();
      })
      .catch(function (error) {
        showBanner(error.message);
      });
  }

  /**
   * The result, read by the host out of the run folder rather than out of its memory, so the
   * tab answers the same way after a restart.
   */
  function refreshResult() {
    if (!state.runDirectory) {
      return Promise.resolve();
    }

    return send('remodel.result', { run_dir: state.runDirectory })
      .then(renderResult)
      .catch(function (error) {
        showBanner(error.message);
      });
  }

  function openCopy() {
    if (!state.runDirectory) {
      return;
    }

    send('remodel.open_copy', { run_dir: state.runDirectory })
      .catch(function (error) {
        showBanner(error.message);
      });
  }

  /**
   * Discard deletes the `.SLDPRT` and keeps every other artifact, which is what the note under
   * the button says and what the host then reports as `kept`.
   */
  function discardCopy() {
    if (!state.runDirectory) {
      return;
    }

    send('remodel.discard_copy', { run_dir: state.runDirectory })
      .then(function (answer) {
        var kept = (answer && answer.kept) || [];
        setRunStatus(
          kept.length
            ? 'The copy is deleted. Still in the run folder: ' + dom.list(kept)
            : 'The copy is deleted.');
        return refreshResult();
      })
      .catch(function (error) {
        showBanner(error.message);
      });
  }

  /**
   * Show one change in SOLIDWORKS. The page sends the sequence number and nothing else: the
   * host holds the persistent reference that change recorded, and resolves it through the same
   * resolver the other two tabs use.
   */
  function showChange(row) {
    var seq = Number(row.getAttribute('data-seq'));
    if (!state.runDirectory || !isFinite(seq)) {
      return;
    }

    send('remodel.show_change', { run_dir: state.runDirectory, change_seq: seq })
      .then(function (shown) {
        if (!shown.ok) {
          showBanner(shown.message || 'that change could not be shown.');
        }
      })
      .catch(function (error) {
        showBanner(error.message);
      });
  }

  // ---- rendering: the run header ---------------------------------------------------------------

  /** The run folder, which is also the only folder anything in this run was written to. */
  function renderRun(runDirectory) {
    state.runDirectory = runDirectory || null;

    dom.clear(ui.runDir);
    dom.write(ui.runDir, runDirectory || '');
    renderControls();
  }

  function renderRunState(runState) {
    dom.clear(ui.runState);
    if (!runState) {
      dom.write(ui.runState, 'No run yet.');
      return;
    }

    var said = RUN_STATES[runState];
    dom.write(
      ui.runState,
      said
        ? 'State: ' + said
        : 'State: ' + runState + ' - not a state this tab knows, so it is reported as the run '
          + 'folder recorded it.');
    ui.runState.setAttribute('data-state', String(runState));
  }

  /**
   * The source attestation: the claim that the engineer's own file was never touched, checked
   * rather than promised. A mismatch is a hard failure of the run however well everything else
   * went, and a re-check that has not run yet is neither answer.
   */
  function renderAttestation(attestation) {
    dom.clear(ui.attestation);
    if (!attestation) {
      dom.write(ui.attestation, 'The source attestation has not been written yet.');
      return;
    }

    var path = dom.scalar(attestation.path);
    if (attestation.matches === true) {
      dom.write(
        ui.attestation,
        'Source unchanged: ' + path + ' is byte for byte what it was when the run started.');
      return;
    }

    if (attestation.matches === false) {
      dom.write(
        ui.attestation,
        'Source changed: ' + path + ' is not what it was when the run started. That is a hard '
          + 'failure of this run, whatever else it reports.');
      return;
    }

    dom.write(
      ui.attestation,
      'The source has not been re-checked yet, so this run makes no claim about ' + path + '.');
  }

  // ---- rendering: the grade ---------------------------------------------------------------------

  /**
   * Both grades as counts per bucket, the fraction secondary, and the unresolved rule ids
   * always named alongside. There is no letter grade and no single percentage headline: a
   * letter is precisely the confident-but-unsupported artifact the constitution forbids.
   */
  function renderGrade(result) {
    dom.clear(ui.grade);
    ui.grade.appendChild(dom.el('h2', 'grade-heading', 'Grade, before and after'));
    ui.grade.appendChild(gradeSide('Before', result ? result.grade_before : null));
    ui.grade.appendChild(gradeSide('After', result ? result.grade_after : null));
  }

  function gradeSide(label, grade) {
    var side = dom.el('section', 'grade-side');
    side.setAttribute('data-side', label.toLowerCase());
    side.appendChild(dom.el('h3', 'side-name', label));

    if (!grade) {
      side.appendChild(dom.el(
        'p',
        'missing',
        'The ' + label.toLowerCase() + ' grade has not been measured yet.'));
      return side;
    }

    var counts = dom.el('ul', 'counts');
    for (var index = 0; index < BUCKETS.length; index++) {
      var bucket = BUCKETS[index];
      var item = dom.el('li', 'count', Number(grade[bucket] || 0) + ' ' + BUCKET_LABELS[bucket]);
      item.setAttribute('data-bucket', bucket);
      counts.appendChild(item);
    }
    side.appendChild(counts);

    side.appendChild(dom.el(
      'p',
      'fraction',
      typeof grade.fraction === 'number'
        ? grade.fraction.toFixed(2) + ' of the rules that reached a verdict were checked'
        : 'No fraction: no rule reached a verdict.'));

    // The unresolved rules travel with the counts, by name. A score with the missing rules
    // named beside it is a grade; a score on its own is a claim.
    var unresolved = grade.unresolved_rule_ids || [];
    side.appendChild(dom.el(
      'p',
      'unresolved-rules',
      unresolved.length
        ? 'Unresolved, so not graded: ' + dom.list(unresolved)
        : 'Every rule reached a verdict.'));

    return side;
  }

  // ---- rendering: the geometry ------------------------------------------------------------------

  /**
   * The geometry gate: the verdict, the quantities it compared, and the statement of what it
   * cannot detect - printed on every run, including a passing one, because a verdict without
   * its coverage reads as "nothing about this part changed" (Principle VI).
   */
  function renderGeometry(result) {
    dom.clear(ui.geometry);
    ui.geometry.appendChild(dom.el('h2', 'geometry-heading', 'Geometry'));

    var geometry = result ? result.geometry : null;
    var gate = geometry ? geometry.gate : null;
    if (!gate) {
      ui.geometry.appendChild(dom.el(
        'p', 'missing', 'The geometry of the copy has not been compared yet.'));
      return;
    }

    var verdict = dom.el('p', 'verdict', 'Verdict: ' + dom.scalar(gate.verdict));
    verdict.setAttribute('data-verdict', String(gate.verdict === undefined ? '' : gate.verdict));
    ui.geometry.appendChild(verdict);

    ui.geometry.appendChild(dom.el(
      'p',
      'profile',
      'Profile ' + dom.scalar(gate.profile) + calibration(geometry.tolerances)));

    if (gate.material_changed) {
      ui.geometry.appendChild(dom.el('p', 'material', 'The material changed during the run.'));
    }

    var deltas = gate.deltas || [];
    var list = dom.el('ul', 'deltas');
    for (var index = 0; index < deltas.length; index++) {
      list.appendChild(deltaRow(deltas[index] || {}));
    }
    ui.geometry.appendChild(list);

    ui.geometry.appendChild(dom.el(
      'h3', 'coverage-heading', 'What this comparison cannot detect'));

    var limits = gate.coverage_limits || [];
    if (!limits.length) {
      // Unknown stays unknown: a gate that recorded no limits is not a gate with none.
      ui.geometry.appendChild(dom.el(
        'p', 'missing', 'This run recorded no coverage limits, which is itself a gap.'));
      return;
    }

    var coverage = dom.el('ul', 'coverage');
    for (var limit = 0; limit < limits.length; limit++) {
      coverage.appendChild(dom.el('li', 'coverage-limit', dom.scalar(limits[limit])));
    }
    ui.geometry.appendChild(coverage);
  }

  function deltaRow(delta) {
    var row = dom.el('li', 'delta');
    row.appendChild(dom.el('span', 'quantity', dom.scalar(delta.quantity)));
    row.appendChild(dom.el(
      'span',
      'delta-values',
      dom.scalar(delta.before) + ' to ' + dom.scalar(delta.after)
        + ' (bound ' + dom.scalar(delta.bound) + ')'));
    row.appendChild(dom.el('span', 'delta-within', delta.within ? 'within' : 'outside'));
    return row;
  }

  function calibration(tolerances) {
    if (!tolerances) {
      return '';
    }
    return tolerances.calibrated
      ? ', calibrated against ' + dom.scalar(tolerances.calibration_ref)
      : ', not calibrated on this workstation yet';
  }

  // ---- rendering: the change list ---------------------------------------------------------------

  /**
   * Every attempted change with its outcome, including the ones that failed and the
   * `attempting` line a crash leaves behind. A list of successes is not a change list.
   */
  function renderChanges(result) {
    var changes = (result && result.changes) || [];

    dom.clear(ui.changesHeading);
    dom.write(ui.changesHeading, 'Changes (' + changes.length + ')');

    var wroteTo = targetPath(changes);
    dom.clear(ui.wroteTo);
    dom.write(ui.wroteTo, wroteTo ? 'Every change was written to ' + wroteTo : '');

    dom.clear(ui.changeList);
    for (var index = 0; index < changes.length; index++) {
      ui.changeList.appendChild(changeRow(changes[index] || {}));
    }

    dom.clear(ui.changesEmpty);
    dom.write(ui.changesEmpty, changes.length ? '' : 'No change has been written yet.');
  }

  /**
   * One `remodel.change` as the host writes it, appended so the list grows while the run is
   * applying rather than appearing all at once at the end.
   */
  function appendChange(change) {
    if (!change) {
      return;
    }

    ui.changeList.appendChild(changeRow(change));
    dom.clear(ui.changesEmpty);
    dom.clear(ui.changesHeading);
    dom.write(
      ui.changesHeading, 'Changes (' + ui.changeList.getElementsByTagName('li').length + ')');
  }

  function changeRow(change) {
    var subject = change.subject || {};
    var row = dom.el('li', 'change');
    row.setAttribute('data-seq', dom.scalar(change.seq));
    row.setAttribute('data-status', dom.scalar(change.status));
    row.setAttribute('data-kind', dom.scalar(change.kind));

    var head = dom.el('div', 'change-head');
    head.appendChild(dom.el('span', 'badge status', dom.scalar(change.status)));
    head.appendChild(dom.el('span', 'kind', dom.scalar(change.kind)));
    head.appendChild(dom.el('span', 'subject-name', dom.scalar(subject.name)));
    head.appendChild(dom.el('span', 'subject-meta', dom.scalar(subject.feature_id)));

    // Offered on every row, including the failed ones: "which feature was that?" is the first
    // question a failed change raises, and the host answers it from the record, not the name.
    head.appendChild(dom.button('Show', 'show', 'action show'));
    row.appendChild(head);

    if (change.error_code || change.error) {
      row.appendChild(dom.el(
        'p',
        'error',
        dom.scalar(change.error_code) + (change.error ? ': ' + dom.scalar(change.error) : '')));
    }

    if (change.status === 'attempting') {
      row.appendChild(dom.el(
        'p',
        'note',
        'Written before the call: if the run stopped here, this names exactly what was in '
          + 'flight.'));
    }

    return row;
  }

  function targetPath(changes) {
    for (var index = changes.length - 1; index >= 0; index--) {
      if (changes[index] && changes[index].target_path) {
        return dom.scalar(changes[index].target_path);
      }
    }
    return '';
  }

  // ---- rendering: the rebuild list --------------------------------------------------------------

  /**
   * Every feature that could not be reorganized, with its reason from the closed taxonomy and
   * the dependency edge that blocked it. This list is the product of stage 1 as much as the
   * change list is: it is what the engineer has to decide about by hand.
   */
  function renderRebuild(result) {
    dom.clear(ui.rebuild);
    var entries = (result && result.rebuild_list) || [];

    ui.rebuild.appendChild(dom.el(
      'h2', 'rebuild-heading', 'Could not be reorganized (' + entries.length + ')'));

    if (!entries.length) {
      ui.rebuild.appendChild(dom.el(
        'p', 'missing', 'Nothing was held back, or the plan has not been read yet.'));
      return;
    }

    var list = dom.el('ul', 'rebuild-list');
    for (var index = 0; index < entries.length; index++) {
      list.appendChild(rebuildRow(entries[index] || {}));
    }
    ui.rebuild.appendChild(list);
  }

  function rebuildRow(entry) {
    var row = dom.el('li', 'entry');
    row.setAttribute('data-reason', dom.scalar(entry.reason));

    var head = dom.el('div', 'entry-head');
    head.appendChild(dom.el('span', 'badge reason', dom.scalar(entry.reason)));
    head.appendChild(dom.el('span', 'entry-name', dom.scalar(entry.name)));
    head.appendChild(dom.el('span', 'entry-meta', dom.scalar(entry.feature_id)));
    row.appendChild(head);

    row.appendChild(dom.el('p', 'detail', dom.scalar(entry.detail)));

    var edge = entry.blocking_edge;
    if (edge) {
      row.appendChild(dom.el(
        'p',
        'edge',
        'Blocking edge: ' + dom.scalar(edge.parent_id) + ' -> ' + dom.scalar(edge.child_id)));
    }

    return row;
  }

  // ---- rendering: the judgement -----------------------------------------------------------------

  /**
   * What the model proposed and what the rules did with it.
   *
   * The rejected proposals are listed with the rule that refused each one rather than omitted
   * (FR-016): a page that showed only what was accepted would report the model as always
   * right. The accepted ones carry the provider and the model that produced them, so "who said
   * this" is answerable on the screen the engineer is already looking at.
   *
   * This is the plan summary `remodel.planned` carried, so it is the plan as it stood when it
   * was written. `report.md` section 7 is the full judgement of the finished run, and the page
   * says so rather than letting a plan-time reading read as a final one.
   */
  function renderPlan(summary) {
    dom.clear(ui.judgement);
    ui.judgement.appendChild(dom.el('h2', 'judgement-heading', 'Judgement'));

    if (!summary) {
      ui.judgement.appendChild(dom.el('p', 'missing', 'No plan has been read yet.'));
      return;
    }

    var descriptions = summary.descriptions || [];
    var globals = summary.globals || [];
    var rejected = summary.rejected_proposals || [];
    var deviations = summary.deviations || [];

    if (!descriptions.length && !globals.length && !rejected.length && !deviations.length) {
      // Before the judgement phase the plan is revision 1 and there is nothing to report yet,
      // which is not the same answer as "the model proposed nothing".
      ui.judgement.appendChild(dom.el(
        'p',
        'missing',
        summary.plan_revision === 1
          ? 'The judgement phase has not run yet.'
          : 'The judgement phase contributed nothing to this plan. That is recorded as a '
            + 'coverage item, not as a pass.'));
      return;
    }

    ui.judgement.appendChild(dom.el(
      'p',
      'note',
      'Read from the plan as it stood when it was written. report.md section 7 is the full '
        + 'judgement of the finished run.'));

    var accepted = dom.el('ul', 'proposals');
    var index;
    for (index = 0; index < descriptions.length; index++) {
      accepted.appendChild(proposalRow('description', descriptions[index] || {}));
    }
    for (index = 0; index < globals.length; index++) {
      accepted.appendChild(proposalRow('global', globals[index] || {}));
    }
    if (descriptions.length || globals.length) {
      ui.judgement.appendChild(dom.el('h3', 'accepted-heading', 'Accepted'));
      ui.judgement.appendChild(accepted);
      ui.judgement.appendChild(dom.el(
        'p',
        'globals-note',
        'Any global added here is written into the equations and drives nothing yet; you wire '
          + 'it to a dimension yourself.'));
    }

    if (rejected.length) {
      ui.judgement.appendChild(dom.el('h3', 'rejected-heading', 'Refused by the rules'));
      var refused = dom.el('ul', 'rejections');
      for (index = 0; index < rejected.length; index++) {
        refused.appendChild(rejectedRow(rejected[index] || {}));
      }
      ui.judgement.appendChild(refused);
    }

    if (deviations.length) {
      ui.judgement.appendChild(dom.el('h3', 'deviations-heading', 'Deviations'));
      var deviated = dom.el('ul', 'deviations');
      for (index = 0; index < deviations.length; index++) {
        deviated.appendChild(deviationRow(deviations[index] || {}));
      }
      ui.judgement.appendChild(deviated);
    }
  }

  function proposalRow(kind, proposal) {
    var row = dom.el('li', 'proposal');
    row.setAttribute('data-kind', kind);

    row.appendChild(dom.el('span', 'badge proposal-kind', kind));
    row.appendChild(dom.el('span', 'proposal-subject', dom.scalar(
      proposal.name === undefined || proposal.name === null
        ? proposal.feature_id
        : proposal.name)));
    row.appendChild(dom.el('span', 'proposal-text', dom.scalar(
      proposal.text === undefined || proposal.text === null
        ? proposal.expression
        : proposal.text)));
    row.appendChild(dom.el('span', 'by', producedBy(proposal)));

    if (proposal.rationale) {
      row.appendChild(dom.el('p', 'rationale', dom.scalar(proposal.rationale)));
    }

    return row;
  }

  function rejectedRow(proposal) {
    var row = dom.el('li', 'rejected');
    row.setAttribute('data-rule', dom.scalar(proposal.rule));

    row.appendChild(dom.el('span', 'tool', dom.scalar(proposal.tool)));
    row.appendChild(dom.el('span', 'rule', dom.scalar(proposal.rule)));
    row.appendChild(dom.el('span', 'reason', dom.scalar(proposal.reason)));
    row.appendChild(dom.el('span', 'by', producedBy(proposal)));

    if (proposal.arguments) {
      row.appendChild(dom.el('p', 'arguments', dom.compact(proposal.arguments)));
    }

    return row;
  }

  function deviationRow(deviation) {
    var row = dom.el('li', 'deviation');
    row.setAttribute('data-kind', dom.scalar(deviation.kind));
    row.appendChild(dom.el('span', 'deviation-subject', dom.scalar(
      deviation.feature_id === undefined ? '' : deviation.feature_id)));
    row.appendChild(dom.el('span', 'deviation-chosen', dom.scalar(deviation.chosen)));
    row.appendChild(dom.el('span', 'deviation-line', dom.scalar(deviation.report_line)));
    return row;
  }

  function producedBy(proposal) {
    var provider = proposal.provider ? String(proposal.provider) : '';
    var model = proposal.model ? String(proposal.model) : '';
    if (!provider && !model) {
      return 'no provider recorded';
    }
    return provider + (model ? ' / ' + model : '');
  }

  // ---- rendering: everything at once --------------------------------------------------------------

  /** The whole result, as the host read it out of the run folder. */
  function renderResult(result) {
    state.result = result || null;

    renderRunState(result ? result.state : null);
    renderAttestation(result ? result.attestation : null);
    renderGrade(state.result);
    renderGeometry(state.result);
    renderChanges(state.result);
    renderRebuild(state.result);
    renderControls();
  }

  // ---- the page's own chrome ------------------------------------------------------------------------

  function renderDocument() {
    dom.clear(ui.documentName);
    var open = state.documentInfo;
    dom.write(
      ui.documentName,
      open && open.path
        ? fileName(open.path) + (open.configuration ? ' [' + open.configuration + ']' : '')
        : 'No document open');

    dom.clear(ui.sourcePath);
    dom.write(ui.sourcePath, (open && open.path) || '');
    renderControls();
  }

  function renderBackendState(text, warn) {
    dom.clear(ui.backendState);
    dom.write(ui.backendState, text);
    ui.backendState.className = warn ? 'badge warn' : 'badge';
  }

  function renderLimits() {
    dom.clear(ui.limits);
    var limits = state.limits;
    if (!limits) {
      return;
    }

    dom.write(
      ui.limits,
      'Limits: ' + dom.scalar(limits.max_changes) + ' changes, '
        + dom.scalar(limits.max_minutes) + ' minutes, '
        + dom.scalar(limits.max_rebuild_seconds) + ' seconds per rebuild. Hitting one stops the '
        + 'run and reports it as truncated.');
  }

  /**
   * Which buttons can be pressed. A part has to be open to plan, a plan has to exist to start,
   * and the copy actions need a run - offered as disabled rather than absent, so the tab says
   * what it can do before it can do it.
   */
  function renderControls() {
    var open = state.documentInfo;
    var busy = state.planning || state.running;
    var hasRun = !!state.runDirectory;

    ui.planRun.disabled = busy || !state.remodelAvailable || !open || !open.path;
    ui.startRun.disabled = busy || !state.remodelAvailable || !hasRun;
    ui.stopRun.disabled = !state.running;
    ui.openCopy.disabled = !hasRun;
    ui.discardCopy.disabled = !hasRun || state.running;
    ui.openReport.disabled = !hasRun;
    ui.openFolder.disabled = !hasRun;
  }

  function showStatus(payload) {
    var stage = payload && payload.stage;

    // The two terminal stages: the host posts one of them once phases B to D have finished,
    // whether they finished, were stopped or failed. They are what ends the running state, and
    // until one of them arrives the run is still running and Stop is still pressable.
    if (stage === 'ready' || stage === 'error') {
      endRun();
    }

    if (stage === 'error') {
      showBanner(payload.message || 'the run stopped');
      return;
    }

    if (stage === 'ready' && !state.backend) {
      // The backend finished starting after this page was given its `init`, so the endpoint it
      // holds is null. Ask again, as the other pages do. Guarded on `state.backend` so the
      // host's own end-of-phase `status {stage: "ready"}` does not re-initialise the page in
      // the middle of a run.
      requestInit();
    }

    setRunStatus((payload && payload.message) || '');
  }

  function showProgress(payload) {
    dom.clear(ui.progress);
    if (!payload) {
      return;
    }

    var current = payload.current || {};
    dom.write(
      ui.progress,
      dom.scalar(payload.applied) + ' of ' + dom.scalar(payload.total) + ' applied'
        + (current.kind
          ? ' - ' + dom.scalar(current.kind) + ' on ' + dom.scalar(current.subject_name)
          : ''));
  }

  function setRunStatus(text) {
    dom.clear(ui.runStatus);
    dom.write(ui.runStatus, text);
  }

  function showBanner(message) {
    dom.clear(ui.banner);
    dom.write(ui.banner, message || '');
    ui.banner.hidden = !message;
  }

  function hideBanner() {
    dom.clear(ui.banner);
    ui.banner.hidden = true;
  }

  /** The last segment of a Windows or POSIX path; the header shows names, not paths. */
  function fileName(path) {
    var text = String(path || '');
    var cut = Math.max(text.lastIndexOf('\\'), text.lastIndexOf('/'));
    return cut >= 0 ? text.substring(cut + 1) : text;
  }

  // ---- wiring ----------------------------------------------------------------------------------------

  function byId(name) {
    return document.getElementById(name);
  }

  function start() {
    ui.documentName = byId('document-name');
    ui.backendState = byId('backend-state');
    ui.banner = byId('banner');
    ui.planRun = byId('plan-run');
    ui.startRun = byId('start-run');
    ui.stopRun = byId('stop-run');
    ui.openCopy = byId('open-copy');
    ui.discardCopy = byId('discard-copy');
    ui.openReport = byId('open-report');
    ui.openFolder = byId('open-folder');
    ui.openLog = byId('open-log');
    ui.sourcePath = byId('source-path');
    ui.runDir = byId('run-dir');
    ui.limits = byId('limits');
    ui.runState = byId('run-state');
    ui.attestation = byId('attestation');
    ui.runStatus = byId('run-status');
    ui.progress = byId('progress');
    ui.grade = byId('grade');
    ui.geometry = byId('geometry');
    ui.changes = byId('changes');
    ui.changesHeading = byId('changes-heading');
    ui.wroteTo = byId('wrote-to');
    ui.changeList = byId('change-list');
    ui.changesEmpty = byId('changes-empty');
    ui.rebuild = byId('rebuild');
    ui.judgement = byId('judgement');

    ui.planRun.addEventListener('click', planRun);
    ui.startRun.addEventListener('click', startRun);
    ui.stopRun.addEventListener('click', stopRun);
    ui.openCopy.addEventListener('click', openCopy);
    ui.discardCopy.addEventListener('click', discardCopy);
    ui.openReport.addEventListener('click', function () {
      openRun('report.open');
    });
    ui.openFolder.addEventListener('click', function () {
      openRun('folder.open');
    });
    ui.openLog.addEventListener('click', function () {
      send('log.open', {}).catch(function (error) {
        showBanner(error.message);
      });
    });

    // One listener for the change list, reading `data-action` off whatever was pressed: no
    // inline handler anywhere, which the CSP would refuse in any case.
    ui.changes.addEventListener('click', onChangeClick);

    if (bridge) {
      bridge.addEventListener('message', onHostMessage);
    }

    renderDocument();
    renderBackendState('Backend starting');
    renderResult(null);
    renderPlan(null);

    requestInit();
  }

  function openRun(type) {
    if (!state.runDirectory) {
      return;
    }

    send(type, { run_dir: state.runDirectory }).catch(function (error) {
      showBanner(error.message);
    });
  }

  /** Ask the host for `init` and apply it. */
  function requestInit() {
    if (state.initPending) {
      return;
    }

    state.initPending = true;
    send('ready', {})
      .then(applyInit)
      .catch(function (error) {
        showBanner(error.message);
      })
      .then(function () {
        state.initPending = false;
      });
  }

  function applyInit(payload) {
    state.backend = payload.backend || null;
    state.token = payload.token || null;
    state.runRoot = payload.run_root || null;
    state.documentInfo = payload.document || null;
    state.limits = payload.limits || null;

    // Older hosts omit this additive capability field; an explicit object is the current
    // host's capability answer (null means it is still being checked).
    var remodel = payload.remodel;
    applyRemodelCapability(remodel);

    renderDocument();
    renderLimits();
    renderBackendState(state.backend ? 'Backend ready' : 'Backend starting', !state.backend);

    if (!state.remodelAvailable) {
      showBanner(state.remodelAvailabilityMessage
        || 'Remodel is unavailable until this build has a remodel seat.');
    }

    var latest = payload.latest_run;
    if (latest && latest.run_dir) {
      renderRun(latest.run_dir);
      refreshResult();
    }
  }

  function applyRemodelCapability(remodel) {
    // Older hosts omit this additive field. An explicit null means capability is still being
    // checked, so keep actions disabled until the tool service publishes its answer.
    if (!remodel) {
      return;
    }

    var wasAvailable = state.remodelAvailable;
    var previousMessage = state.remodelAvailabilityMessage;
    state.remodelAvailable = remodel.available === true;
    state.remodelAvailabilityMessage = remodel.message
      ? String(remodel.message)
      : null;

    if (!state.remodelAvailable && state.remodelAvailabilityMessage) {
      showBanner(state.remodelAvailabilityMessage);
    } else if (state.remodelAvailable
        && !wasAvailable
        && previousMessage
        && ui.banner.textContent === previousMessage) {
      // Clear only the banner this capability check created; an unrelated error that arrived
      // while the seat was attaching remains visible for the engineer.
      hideBanner();
    }
    renderControls();
  }

  function onChangeClick(event) {
    var pressed = closestAction(event.target);
    if (!pressed || pressed.getAttribute('data-action') !== 'show') {
      return;
    }

    showChange(closestClass(pressed, 'change'));
  }

  function closestAction(node) {
    while (node && node !== document) {
      if (node.getAttribute && node.getAttribute('data-action')) {
        return node;
      }
      node = node.parentNode;
    }
    return null;
  }

  function closestClass(node, className) {
    while (node && node !== document) {
      if (node.classList && node.classList.contains(className)) {
        return node;
      }
      node = node.parentNode;
    }
    return null;
  }

  window.SwReviewRemodel = {
    renderRun: renderRun,
    renderResult: renderResult,
    renderPlan: renderPlan,
    appendChange: appendChange
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
