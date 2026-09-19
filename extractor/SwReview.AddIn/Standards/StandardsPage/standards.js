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

  /** What separates two facts inside one line, the same mark the shared half uses. */
  var DOT = ' · ';

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
   * The colour each headline is set in, as a class on the block that holds it.
   *
   * A map from the state to a class name, beside the map from the state to the words: the two
   * are the same decision said twice, and the page must never be able to print one headline in
   * another headline's colour. Nothing here reads a severity or a status - there is no ranking
   * in a release gate, only which of three things the run concluded. A state this page has
   * never heard of gets the neutral ground, the same way its headline says so in words.
   */
  var HEADLINE_TONES = {
    ready: 'verdict-good',
    not_ready: 'verdict-critical',
    ready_coverage_incomplete: 'verdict-warn'
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
   *
   * One tinted block holds the headline and everything that qualifies it - which document, what
   * reached no verdict, every note, and whether anything was rebuilt - because each of those is
   * a reason the headline says less than it seems, and a note two blocks below a clean headline
   * is a note nobody reads. The counts sit under that block, as a table rather than a sentence:
   * the seven do not share a unit and a reader who added them up would be wrong.
   */
  function renderVerdict(result, node) {
    var roster = document.getElementById('checks');
    dom.clear(roster);

    if (!result || !result.verdict) {
      return;
    }

    var verdict = result.verdict;
    var block = dom.el('div', 'verdict-block ' + tone(verdict));
    block.appendChild(dom.el('h2', 'verdict-headline', headline(verdict)));
    block.appendChild(dom.el('p', 'verdict-document', subject(result)));

    // The unresolved checks travel with the counts, by name, in every state. A headline with
    // the missing checks named beside it is a verdict; a headline on its own is a claim.
    block.appendChild(unresolvedLine(verdict.unresolved_check_ids || []));

    // What the headline was reached with: a waiver, an empty profile list, a run that graded no
    // drawing. Beside the headline, because each of them is a reason it says less than it seems.
    var notes = verdict.notes || [];
    for (var note = 0; note < notes.length; note++) {
      block.appendChild(dom.el('p', 'verdict-note', notes[note]));
    }

    if (result.rebuilt === false) {
      block.appendChild(dom.el(
        'p',
        'not-rebuilt',
        'Nothing was rebuilt: the counts are as the documents stood when they were read.'));
    }

    node.appendChild(block);

    var counts = dom.el('ul', 'counts');
    for (var index = 0; index < COUNTS.length; index++) {
      var row = COUNTS[index];

      // The number leads, in its own cell, so seven rows in seven different units line up as a
      // table; the row still reads "<n> <label> <unit>", which is what the contract pins.
      var item = dom.el('li', 'count');
      item.appendChild(dom.el('b', 'count-n', countOf(verdict, row.key)));
      item.appendChild(dom.el('span', 'count-label', ' ' + row.label + ' ' + row.unit));
      item.setAttribute('data-count', row.key);
      counts.appendChild(item);
    }
    node.appendChild(counts);

    renderChecks(result.checks || [], roster);
  }

  function headline(verdict) {
    var state = String(verdict.state || '');
    return HEADLINES[state] || ('The run reported a state this page does not know: ' + state);
  }

  /** Which colour the block is set in, from the same state the headline was chosen by. */
  function tone(verdict) {
    return HEADLINE_TONES[String(verdict.state || '')] || 'verdict-unknown';
  }

  /** The checks that reached no verdict, named in the mono face so they read as names. */
  function unresolvedLine(unresolved) {
    var line = dom.el('p', 'unresolved-checks');
    if (!unresolved.length) {
      dom.write(line, 'Every check reached a verdict.');
      return line;
    }

    dom.write(line, 'Unresolved, so not graded: ');
    line.appendChild(dom.el('span', 'mono', dom.list(unresolved)));
    return line;
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

    // Behind one press, with the tally on the closed summary. The roster repeats, on purpose,
    // what the rows below already show - so it has to be reachable and it must not be the thing
    // between the release headline and the rules. Closed, it is one line that says all sixteen
    // were accounted for; open, it says where each of them landed.
    var fold = dom.el('details', 'checks-fold');
    var summary = dom.el('summary', 'checks-summary');
    summary.appendChild(dom.el('span', 'checks-heading', 'All ' + checks.length + ' checks'));
    summary.appendChild(dom.el('span', 'checks-tally', tally(checks)));
    fold.appendChild(summary);

    var list = dom.el('ul', 'check-list');
    for (var index = 0; index < checks.length; index++) {
      list.appendChild(checkRow(checks[index] || {}));
    }
    fold.appendChild(list);

    node.appendChild(fold);
  }

  /**
   * How the sixteen landed, as one line on the closed fold.
   *
   * Counted, never ordered: the buckets are stated in the check page's own display order and the
   * numbers are read off the rows. A bucket nothing landed in is left out rather than printed as
   * a zero, because a line of zeroes is what an engineer stops reading.
   */
  function tally(checks) {
    var counted = Object.create(null);
    var index;
    for (index = 0; index < checks.length; index++) {
      var worst = String((checks[index] || {}).worst_bucket || '');
      counted[worst] = (counted[worst] || 0) + 1;
    }

    var parts = [];
    for (index = 0; index < shared.BUCKETS.length; index++) {
      var bucket = shared.BUCKETS[index];
      if (counted[bucket]) {
        parts.push(counted[bucket] + ' ' + shared.BUCKET_LABELS[bucket]);
      }
    }
    return parts.join(DOT);
  }

  /**
   * One check: a line, and a fold of its own.
   *
   * The line is a dot in the worst bucket's colour, the check id and its severity - which is as
   * much as a reference list needs to be read down. The statement and the bucket-by-bucket
   * detail are one more press away, and still in the DOM either way: the roster's whole job is
   * that a check which applied to nothing is present rather than absent.
   */
  function checkRow(check) {
    var worst = String(check.worst_bucket || '');
    var item = dom.el('li', 'check');
    item.setAttribute('data-check', String(check.check || ''));
    item.setAttribute('data-worst-bucket', worst);

    var fold = dom.el('details', 'check-fold');
    var head = dom.el('summary', 'check-head');
    head.appendChild(dom.el('span', 'check-dot bucket-' + (worst || 'none'), ''));
    head.appendChild(dom.el('span', 'check-id', String(check.check || '')));
    head.appendChild(dom.el('span', 'check-severity', String(check.severity || '')));

    // A dot cannot say "the run never told us", and a grey one would read as skipped. Only the
    // case that has no bucket at all says so in words.
    if (!worst) {
      head.appendChild(dom.el('span', 'check-worst', 'not reported'));
    }
    fold.appendChild(head);

    if (check.statement) {
      fold.appendChild(dom.el('p', 'statement', check.statement));
    }

    var buckets = check.buckets || [];
    var list = dom.el('ul', 'check-buckets');
    for (var index = 0; index < buckets.length; index++) {
      list.appendChild(bucketRow(buckets[index] || {}));
    }
    fold.appendChild(list);

    item.appendChild(fold);
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
