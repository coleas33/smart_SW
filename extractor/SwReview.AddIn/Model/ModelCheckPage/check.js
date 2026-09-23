/*
  The Model check page's own half (T082, contracts/model-check.md; extracted T030).

  Almost all of what this page does it does the same way the Standards check page does, and that
  half lives in `shared/check-page.js`: the host channel, the authenticated `call` wrapper, the
  check a previous press left behind, the bucket chips, the coverage and finding renderers, the
  Show and Accept flows and the page's chrome. Two copies of that would be two copies of the
  rules about what an engineer is allowed not to see and about which strings reach the DOM as
  text, and the second copy is the one that goes out of date.

  What is here is what is about the RMS rule family and nothing else:

  1. The grade header - the bucket counts, and the rules that reached no verdict named beside
     them by their statements (feature 009 FR-028). The Standards page renders a verdict into the
     same slot.
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

  /**
   * The grade, into the slot the shared half has just cleared.
   *
   * A summary rather than a headline: the thing to act on is the list below, not the score. So
   * the heading is an eyebrow, the six counts are one muted inline row, and the rules that
   * reached no verdict follow in words.
   */
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

      // The number leads, in its own element, and the label reads after it - so the row still
      // says "<n> <label>" and a reader's eye still lands on the number.
      var item = dom.el('li', 'count');
      item.appendChild(dom.el('b', 'count-n', count));
      item.appendChild(dom.el('span', 'count-label', ' ' + BUCKET_LABELS[bucket]));
      item.setAttribute('data-bucket', bucket);
      counts.appendChild(item);
    }
    node.appendChild(counts);

    if (total === 0) {
      // Not a perfect score: nothing reached a bucket at all (T068).
      node.appendChild(dom.el('p', 'nothing-evaluated', 'Nothing was evaluated.'));
      return;
    }

    // The unresolved rules travel with the counts, by what they say. A score with the missing
    // rules named beside it is a grade; a score on its own is a claim. Named by statement since
    // feature 009 (FR-028): the fraction of the rules that reached a verdict is a number only its
    // author reads, and it stays in the body and the report; the rule ids are behind a fold.
    node.appendChild(unresolvedRules(grade.unresolved_rule_ids || [], result.rule_statements));
  }

  /**
   * The rules that reached no verdict: "Not graded, evidence missing:" and each rule's statement
   * - the backend's `RULES` text, `rule_statements` on the body - with the ids in a shut fold, in
   * the mono face so they read as names. A rule the catalogue has no statement for, and every rule
   * on a body with no `rule_statements` (a backend before feature 009), is named by its id rather
   * than dropped. None unresolved says so in words.
   */
  function unresolvedRules(unresolved, statements) {
    var block = dom.el('div', 'unresolved-rules');
    if (!unresolved.length) {
      block.appendChild(dom.el('p', 'unresolved-lead', 'Every rule reached a verdict.'));
      return block;
    }

    block.appendChild(dom.el('p', 'unresolved-lead', 'Not graded, evidence missing:'));
    var list = dom.el('ul', 'unresolved-statements');
    for (var index = 0; index < unresolved.length; index++) {
      list.appendChild(dom.el('li', '', statementOf(statements, unresolved[index])));
    }
    block.appendChild(list);

    var fold = dom.el('details', 'unresolved-ids');
    fold.appendChild(dom.el('summary', '', 'Rule ids'));
    fold.appendChild(dom.el('p', 'mono', dom.list(unresolved)));
    block.appendChild(fold);
    return block;
  }

  /** A rule's statement from the body's map - an own string property only - or its id. */
  function statementOf(statements, ruleId) {
    var id = String(ruleId);
    var statement = (statements && Object.prototype.hasOwnProperty.call(statements, id)) ? statements[id] : null;
    return typeof statement === 'string' && statement ? statement : id;
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
