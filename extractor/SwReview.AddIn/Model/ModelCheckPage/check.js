/*
  The Model check page's own half (T082, contracts/model-check.md; extracted T030).

  Almost all of what this page does it does the same way the Standards check page does, and that
  half lives in `shared/check-page.js`: the host channel, the authenticated `call` wrapper, the
  check a previous press left behind, the bucket chips, the coverage and finding renderers, the
  Show and Accept flows and the page's chrome. Two copies of that would be two copies of the
  rules about what an engineer is allowed not to see and about which strings reach the DOM as
  text, and the second copy is the one that goes out of date.

  What is here is what is about the RMS rule family and nothing else:

  1. The grade header - the bucket counts, the fraction, and the rules that reached no verdict
     named beside it. The Standards page renders a verdict into the same slot.
  2. The start verb: one press of Model check, against this family's scope and this family's
     evaluation route.

  Both halves obey the same rules. Markup is never assigned and no handler is inline: every node
  is built through `shared/dom.js` (T080), which is the single place the "insert every untrusted
  string with createTextNode" rule lives. The untrusted text here is a feature name and an
  `observed` string assembled out of feature names - authored by whoever last renamed a feature
  in the part, which on a supplied model is not anyone this workstation knows. And `renderResult`
  is exported for the page tests, which call it inside the real page under the real CSP; the tab
  renders through the same function, so a row a test built behaves exactly like a row the tab
  built.
*/

(function () {
  'use strict';

  var dom = window.SwReviewDom;
  var shared = window.SwReviewCheckPage;

  /** The buckets and their labels are the check page's, not this family's. */
  var BUCKETS = shared.BUCKETS;
  var BUCKET_LABELS = shared.BUCKET_LABELS;

  /** The only scope this increment evaluates (contracts/model-check.md). */
  var SCOPE = 'part';

  /** This family's evaluation route. */
  var CHECK_ROUTE = '/checks/rms'; // called through the shared call wrapper, which puts the token in the Authorization header as 'Bearer ' + token and never in a URL (chat-api.md)

  var page = shared.create({
    /** The slot the header renders into; a verdict goes in the same place on the other tab. */
    headerId: 'grade',
    renderHeader: renderGrade,
    startCheck: startCheck,
    describeCounts: describeCounts,

    // What a waiver binds to, in words. This family grades parts, so the label says "part";
    // the Standards tab grades parts, assemblies and drawings and says "document"
    // (contracts/model-check.md section 5).
    acceptLabel: 'Accept this rule for this part',
    acceptNoteHint: 'Why this is acceptable on this part (required)'
  });

  // ---- the start verb ----------------------------------------------------------------------

  /**
   * One press of Model check: the host extracts, the page grades.
   *
   * The split is the contract's. The host owns the run folder and the in-process dump because
   * only it can reach SOLIDWORKS; the page owns `POST /checks/rms` because there is exactly one
   * evaluation entry point and it is in the backend, and because a graded part's findings and
   * subjects are more than a `postMessage` channel should carry.
   */
  function startCheck(api) {
    if (api.checking()) {
      return;
    }

    api.setChecking(true);
    api.hideBanner();
    api.setCheckState('Reading the feature tree...');

    api.send('check.start', { scope: SCOPE })
      .then(function (extracted) {
        api.setRunDirectory(extracted.run_dir);
        api.setCheckState('Checking the model...');
        return api.call(CHECK_ROUTE, 'POST', {
          run_dir: extracted.run_dir,
          scope: SCOPE,
          document_id: null
        });
      })
      .then(function (result) {
        api.renderResult(result);
        api.setCheckState('Checked ' + describeCounts(result));
      })
      .catch(function (error) {
        api.showBanner(error.message);
        api.setCheckState('');
      })
      .then(function () {
        api.setChecking(false);
      });
  }

  /**
   * The sentence the button leaves behind, off this family's `grade`. It is here rather than in
   * the shared half because `grade` is this family's headline object and its buckets are this
   * family's: a standards result carries a `verdict` instead, with a state, a waived count and
   * its own buckets (contracts/standards-check.md D3).
   */
  function describeCounts(result) {
    var grade = (result && result.grade) || {};
    return Number(grade.failed || 0) + ' failed, ' + Number(grade.warned || 0) + ' warned, '
      + Number(grade.checked || 0) + ' checked.';
  }

  // ---- the grade header ----------------------------------------------------------------------

  /** The grade, into the slot the shared half has just cleared. */
  function renderGrade(result, node) {
    if (!result || !result.grade) {
      return;
    }

    var grade = result.grade;
    node.appendChild(dom.el('h2', 'grade-heading', gradeHeading(result)));

    var total = 0;
    var counts = dom.el('ul', 'counts');
    for (var index = 0; index < BUCKETS.length; index++) {
      var bucket = BUCKETS[index];
      var count = Number(grade[bucket] || 0);
      total += count;
      var item = dom.el('li', 'count', count + ' ' + BUCKET_LABELS[bucket]);
      item.setAttribute('data-bucket', bucket);
      counts.appendChild(item);
    }
    node.appendChild(counts);

    if (total === 0) {
      // Not a perfect score: nothing reached a bucket at all (T068).
      node.appendChild(dom.el('p', 'nothing-evaluated', 'Nothing was evaluated.'));
      return;
    }

    node.appendChild(dom.el(
      'p',
      'fraction',
      typeof grade.fraction === 'number'
        ? grade.fraction.toFixed(2) + ' of the rules that reached a verdict were checked'
        : 'No fraction: no rule reached a verdict.'));

    // The unresolved rules travel with the counts, by name. A score with the missing rules
    // named beside it is a grade; a score on its own is a claim.
    var unresolved = grade.unresolved_rule_ids || [];
    node.appendChild(dom.el(
      'p',
      'unresolved-rules',
      unresolved.length
        ? 'Unresolved, so not graded: ' + dom.list(unresolved)
        : 'Every rule reached a verdict.'));
  }

  function gradeHeading(result) {
    var document_ = result.document;
    return document_ && document_.path
      ? 'Grade: ' + shared.fileName(document_.path)
        + (document_.configuration ? ' [' + document_.configuration + ']' : '')
      : 'Grade';
  }

  window.SwReviewCheck = {
    renderResult: page.renderResult
  };
})();
