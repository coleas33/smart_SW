/*
  The Standards page's own half (T079, contracts/standards-check.md).

  Almost all of what this page does it does the same way the Model check page does, and that
  half lives in `shared/check-page.js`: the host channel, the authenticated `call` wrapper, the
  check a previous press left behind, the bucket chips, the coverage and finding renderers, the
  Show and Accept flows and the page's chrome. Two copies of that would be two copies of the
  rules about what an engineer is allowed not to see and about which strings reach the DOM as
  text, and the second copy is the one that goes out of date.

  What is here is what is about the release checklist and nothing else:

  1. The verdict header - a state, the counts in every bucket with the unit each one counts,
     the unresolved check ids named beside them in every state, and the notes that stop a clean
     headline hiding a waiver, an empty profile list or a run that graded no drawing. The Model
     check page renders a grade into the same slot; this family has no grade, no fraction and
     no percentage, because "ready to release" is not a score.
  2. All sixteen checks, each with every bucket it landed in, the documents in it and the
     reason. A check that did not apply is present with an out-of-scope bucket rather than
     absent, so a release gate can say "all sixteen were accounted for" from one list.
  3. The start verb: one press of Standards check, against this family's evaluation route - and
     carrying the `profile_path` this page was given in `init`, because the reasoning side owns
     the profile schema. The PATH travels; no profile value ever does, in either direction.
  4. What would be graded, from the open document's kind. All three kinds are gradable here, so
     `kind` says *what* rather than *whether* - and a drawing-rooted run fans out to every model
     its views reference, which an engineer should read before pressing, not after.

  Both halves obey the same rules. Markup is never assigned and no handler is inline: every node
  is built through `shared/dom.js` (T080), which is the single place the "insert every untrusted
  string with createTextNode" rule lives. The untrusted text here is a component name, an
  `observed` string assembled out of component names, and a revision-table cell - the last of
  which was typed by whoever drew a drawing that may have arrived from a supplier. And
  `renderResult` is exported for the page tests, which call it inside the real page under the
  real CSP; the tab renders through the same function, so a row a test built behaves exactly
  like a row the tab built.
*/

(function () {
  'use strict';

  var dom = window.SwReviewDom;
  var shared = window.SwReviewCheckPage;

  /** This family's evaluation route. The token goes in the header, never in this URL. */
  var CHECK_ROUTE = '/checks/standards';

  /**
   * The three verdict states and their headlines (FR-032).
   *
   * "Ready to release" is reachable only at zero errors and zero unresolved checks. The third
   * state is deliberately not worded as a kind of ready: a run that did not cover everything
   * has not proved anything about what it did not cover, and an engineer skimming a headline
   * reads the first two words.
   */
  var HEADLINES = {
    ready: 'Ready to release',
    not_ready: 'Not ready to release',
    ready_coverage_incomplete: 'Not proven ready: the run left checks without a verdict'
  };

  /**
   * The counts, in the order the header states them, each with the unit it counts.
   *
   * The unit is rendered rather than assumed because the seven do not share one: the first
   * three count findings - one per failing check per document - and the last four count
   * (check, document) pairs, so they do not sum to sixteen and a reader who added them up
   * would be wrong.
   */
  var COUNTS = [
    { key: 'error', label: 'error', unit: 'findings' },
    { key: 'warning', label: 'warning', unit: 'findings' },
    { key: 'waived', label: 'waived', unit: 'findings' },
    { key: 'checked', label: 'checked', unit: '(check, document) pairs' },
    { key: 'skipped', label: 'skipped', unit: '(check, document) pairs' },
    { key: 'unresolved', label: 'unresolved', unit: '(check, document) pairs' },
    { key: 'out_of_scope', label: 'out of scope', unit: '(check, document) pairs' }
  ];

  /** What a check run rooted at each kind of document would grade. */
  var GRADES = {
    part: 'this part',
    assembly: 'this assembly and everything under it',
    drawing: 'this drawing and the models its views reference'
  };

  /** What the host refuses by name, said here so the button is never offered for it. */
  var UNGRADABLE = 'A standards check grades a part, an assembly or a drawing.';

  /** The configured profile path, from `init`. A path, and never a value out of the file. */
  var profilePath = null;

  var page = shared.create({
    headerId: 'verdict',
    renderHeader: renderVerdict,
    startCheck: startCheck,
    describeCounts: describeCounts,
    onInit: applyProfile,
    onDocument: sayWhatWouldBeGraded,

    // What a waiver binds to, in words. This family grades parts, assemblies and drawings, so
    // the label says "document": an engineer waiving a drawing check must see that every
    // dimension on that drawing is covered for as long as the fingerprint holds
    // (contracts/standards-check.md section 5, difference D12).
    acceptLabel: 'Accept this check for this document',
    acceptNoteHint: 'Why this is acceptable on this document (required)'
  });

  // ---- the start verb ------------------------------------------------------------------------

  /**
   * One press of Standards check: the host extracts, the page grades.
   *
   * The split is the contract's. The host owns the run folder and the in-process dump because
   * only it can reach SOLIDWORKS; the page owns the evaluation call because there is exactly
   * one evaluation entry point and it is in the backend, and because sixteen check rows across
   * every document a drawing reaches is more than a `postMessage` channel should carry.
   *
   * The failure path clears the result rather than leaving it. A refusal can arrive *after* a
   * run folder was created - the dump succeeded and the backend then refused the profile - and
   * the last run's verdict left on screen beside this run's folder reads as this run's answer,
   * which is the one thing a release gate must never do.
   */
  function startCheck(api) {
    if (api.checking()) {
      return;
    }

    api.setChecking(true);
    api.hideBanner();
    api.setCheckState('Extracting the documents...');

    api.send('standards.start', {})
      .then(function (extracted) {
        api.setRunDirectory(extracted.run_dir);
        api.setCheckState('Checking against the release standards...');
        return api.call(CHECK_ROUTE, 'POST', {
          run_dir: extracted.run_dir,

          // The path this page was handed in `init`, relayed. The backend reads the file: the
          // schema is expressed in exactly one place and this is not it (FR-002).
          profile_path: profilePath
        });
      })
      .then(function (result) {
        api.renderResult(result);
        api.setCheckState('Checked. ' + describeCounts(result));
      })
      .catch(function (error) {
        api.renderResult(null);
        api.showBanner(error.message);
        api.setCheckState('');
      })
      .then(function () {
        api.setChecking(false);
      });
  }

  /**
   * The sentence the button leaves behind, off this family's `verdict`. It is here rather than
   * in the shared half because the headline object is this family's and so are its buckets: an
   * RMS result carries a grade with a fraction instead (contracts/standards-check.md D3).
   */
  function describeCounts(result) {
    var counts = (result && result.verdict && result.verdict.counts) || {};
    return Number(counts.error || 0) + ' error, ' + Number(counts.warning || 0) + ' warning, '
      + Number(counts.unresolved || 0) + ' unresolved.';
  }

  // ---- the verdict header ----------------------------------------------------------------------

  /**
   * The verdict, into the slot the shared half has just cleared, and the sixteen checks into
   * the list beside it - which this page owns, so this page clears it.
   */
  function renderVerdict(result, node) {
    var roster = document.getElementById('checks');
    dom.clear(roster);

    if (!result || !result.verdict) {
      return;
    }

    var verdict = result.verdict;
    node.appendChild(dom.el('h2', 'verdict-headline', headline(verdict)));
    node.appendChild(dom.el('p', 'verdict-document', subject(result)));

    var counts = dom.el('ul', 'counts');
    for (var index = 0; index < COUNTS.length; index++) {
      var row = COUNTS[index];
      var item = dom.el(
        'li', 'count', countOf(verdict, row.key) + ' ' + row.label + ' ' + row.unit);
      item.setAttribute('data-count', row.key);
      counts.appendChild(item);
    }
    node.appendChild(counts);

    // The unresolved checks travel with the counts, by name, in every state. A headline with
    // the missing checks named beside it is a verdict; a headline on its own is a claim.
    var unresolved = verdict.unresolved_check_ids || [];
    node.appendChild(dom.el(
      'p',
      'unresolved-checks',
      unresolved.length
        ? 'Unresolved, so not graded: ' + dom.list(unresolved)
        : 'Every check reached a verdict.'));

    // What the headline was reached with: a waiver, an empty profile list, a run that graded no
    // drawing. Beside the headline, because each of them is a reason it says less than it seems.
    var notes = verdict.notes || [];
    for (var note = 0; note < notes.length; note++) {
      node.appendChild(dom.el('p', 'verdict-note', notes[note]));
    }

    if (result.rebuilt === false) {
      node.appendChild(dom.el(
        'p',
        'not-rebuilt',
        'Nothing was rebuilt: the counts are as the documents stood when they were read.'));
    }

    renderChecks(result.checks || [], roster);
  }

  function headline(verdict) {
    var state = String(verdict.state || '');
    return HEADLINES[state] || ('The run reported a state this page does not know: ' + state);
  }

  /** Which document was graded, and against which profile file. Never a profile value. */
  function subject(result) {
    var document_ = result.document || {};
    var graded = (result.documents_graded || []).length;
    var name = document_.path ? shared.fileName(document_.path) : 'the open document';
    return name
      + (document_.configuration ? ' [' + document_.configuration + ']' : '')
      + (graded ? ', with ' + graded + ' document(s) graded' : '');
  }

  function countOf(verdict, key) {
    if (key === 'waived') {
      return Number(verdict.waived || 0);
    }
    return Number((verdict.counts || {})[key] || 0);
  }

  // ---- all sixteen checks ------------------------------------------------------------------------

  /**
   * Every check the family has, whether it applied or not, each with the buckets it landed in.
   *
   * Read off the result's own `checks` array rather than derived from the rows below it: a
   * check that applied to no document produces neither a finding nor a coverage row, so a page
   * that derived this list would quietly render fifteen and call it sixteen (FR-033).
   */
  function renderChecks(checks, node) {
    if (!checks.length) {
      return;
    }

    var list = dom.el('ul', 'check-list');
    for (var index = 0; index < checks.length; index++) {
      list.appendChild(checkRow(checks[index] || {}));
    }

    node.appendChild(dom.el('h2', 'checks-heading', 'All ' + checks.length + ' checks'));
    node.appendChild(list);
  }

  function checkRow(check) {
    var worst = String(check.worst_bucket || '');
    var item = dom.el('li', 'check');
    item.setAttribute('data-check', String(check.check || ''));
    item.setAttribute('data-worst-bucket', worst);

    var head = dom.el('div', 'check-head');
    head.appendChild(dom.el(
      'span', 'badge bucket', shared.BUCKET_LABELS[worst] || worst || 'not reported'));
    head.appendChild(dom.el('span', 'check-id', String(check.check || '')));
    head.appendChild(dom.el('span', 'check-severity', String(check.severity || '')));
    item.appendChild(head);

    if (check.statement) {
      item.appendChild(dom.el('p', 'statement', check.statement));
    }

    var buckets = check.buckets || [];
    var list = dom.el('ul', 'check-buckets');
    for (var index = 0; index < buckets.length; index++) {
      list.appendChild(bucketRow(buckets[index] || {}));
    }
    item.appendChild(list);

    return item;
  }

  /** One bucket of one check: which bucket, which documents landed in it, and why. */
  function bucketRow(bucket) {
    var name = String(bucket.bucket || '');
    var documents = bucket.document_ids || [];
    var row = dom.el(
      'li',
      'check-bucket',
      (shared.BUCKET_LABELS[name] || name) + ': ' + dom.list(documents)
        + (bucket.reason ? ' - ' + bucket.reason : ''));
    row.setAttribute('data-bucket', name);
    return row;
  }

  // ---- the page's own chrome -----------------------------------------------------------------------

  /**
   * Which profile file is in force, from `init`.
   *
   * The page shows the path and sends it on its own request, and that is the whole of its
   * involvement with the profile: no value out of the file ever reaches this process, in
   * either direction (FR-001, FR-002).
   */
  function applyProfile(payload) {
    profilePath = (payload && payload.profile_path) || null;

    var node = document.getElementById('profile');
    dom.clear(node);
    dom.write(
      node,
      profilePath
        ? 'Standards profile: ' + profilePath
        : 'No standards profile is configured, so a check would be refused. '
          + 'Set StandardsProfilePath under Settings.');
  }

  /**
   * What would be graded if the button were pressed now.
   *
   * All three kinds are gradable, so the kind says *what* rather than *whether* (D11) - and a
   * kind the host refuses gets no button at all rather than a button whose only answer is a
   * refusal.
   */
  function sayWhatWouldBeGraded(open) {
    var node = document.getElementById('grading');
    dom.clear(node);

    if (!open || !open.path) {
      return;
    }

    var graded = GRADES[String(open.kind || '')];
    dom.write(node, graded ? 'Standards check would grade ' + graded + '.' : UNGRADABLE);

    if (!graded) {
      document.getElementById('run-check').disabled = true;
    }
  }

  window.SwReviewStandards = {
    renderResult: page.renderResult
  };
})();
