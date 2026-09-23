/*
  The Start-here renderer every tab that shows the ranking shares (feature 009 increment 3).

  `report/attention.py` ranks a finished session once, and `report.md`, the Model check tab,
  the Standards tab and the Review tab all print the rows they are handed, in the order they
  were handed them (contracts/attention.md sections 3 and 6). The row itself - which finding,
  the reason the policy placed it, its title, its check, its state and the stripe that restates
  its consequence class - was written twice, once in the Review page's `render.js` and once in
  `web/shared/check-page.js`, and the two copies had already drifted apart. It is written once
  here, loaded by all three pages after `dom.js` and before the script that renders with it.

  What each page keeps is its own panel: the Review tab wraps the rows in a section of its own,
  with a count line and the rows beyond `top_n` behind "Show all"; a check tab appends them to
  the section its `index.html` already has. Those differ, so they are not here.

  Nothing here reads a severity, compares two rows, or sorts: the order of the rows is the
  ranking's whole statement, and `PageRuleScanTests` scans this file with every page's. Every
  node is built through `dom.js`, the one place a string becomes a text node - a reason line is
  assembled from a finding's own fields, and a finding's title was written by a language model
  reading a reviewed assembly (FR-029).
*/

(function () {
  'use strict';

  var dom = window.SwReviewDom;

  /**
   * The heading over the ranked rows. The same words the report's own section uses, because it
   * is the same ranking: an engineer who reads a tab and then opens `report.md` must find the
   * same rows under the same name (contracts/attention.md section 3).
   */
  var HEADING = 'Start here';

  /**
   * The separator between the small facts that share a line. An escape rather than the
   * character itself, so this file stays ASCII.
   */
  var DOT = ' \u00b7 ';

  /**
   * The stripe a ranked row carries, by the consequence class the backend already assigned it
   * (contracts/attention.md section 1, key 3). An object literal rather than an array: this is
   * a map from a class the policy named to a hue, and it puts nothing before anything.
   */
  var CONSEQUENCE_STRIPE = {
    rebuild_breaker: 'stripe-critical',
    manufacturing: 'stripe-critical',
    interface: 'stripe-judge',
    discipline: 'stripe-warn',
    hygiene: 'stripe-quiet',
    unclassified: 'stripe-quiet'
  };

  /**
   * The stripe for a row only an engineer can settle. It is read off the ranking's own key -
   * `key.judgement`, contracts/attention.md section 1 key 2, where 0 means "needs your
   * judgement" - and not off the row's severity or status, which no page compares.
   */
  var JUDGEMENT_STRIPE = 'stripe-judge';

  /** A consequence class the map does not name still gets a stripe, the quietest one. */
  var DEFAULT_STRIPE = 'stripe-quiet';

  /**
   * The first `top_n` rows: the ones the policy chose to put under Start here. `rows` holds
   * every row the policy ranked, suppressed ones last. A ranking carrying no usable `top_n`
   * gives back what it was given rather than nothing.
   */
  function amplified(ranking) {
    var rows = ranking.rows || [];
    var count = ranking.top_n;
    return (typeof count === 'number' && count >= 0 && count < rows.length)
      ? rows.slice(0, count)
      : rows;
  }

  /**
   * The rows as the numbered list both kinds of tab show under Start here, in the order given.
   * `options` is handed to every row's meta line unchanged (see `attentionMeta`); the check tabs
   * pass none.
   */
  function rowList(rows, options) {
    var list = dom.el('ol', 'attention-rows');
    for (var index = 0; index < rows.length; index++) {
      list.appendChild(attentionRow(rows[index] || {}, options));
    }
    return list;
  }

  /**
   * One ranked row: which finding, the reason the policy placed it, what it says, which check
   * said it, the state it is in, and - when the backend persisted one - the plain-language
   * explanation of it (contracts/attention.md section 6, U5).
   *
   * The stripe is the one piece of colour here, and it restates a field rather than adding a
   * judgement of its own: `consequence_class` through a map, or the judgement key when the
   * policy marked the row as one only an engineer can settle.
   */
  function attentionRow(row, options) {
    var item = dom.el('li', 'attention-row ' + stripeOf(row));
    item.setAttribute('data-finding-id', String(row.finding_id || ''));
    dom.append(item, [
      dom.el('span', 'attention-id', row.finding_id || ''),
      dom.el('span', 'attention-reason', row.reason || ''),
      dom.el('span', 'attention-title', row.title || ''),
      dom.el('span', 'attention-check', row.check || ''),
      attentionMeta(row, options)
    ]);
    if (typeof row.explanation === 'string' && row.explanation) {
      item.appendChild(dom.el('p', 'finding-explanation', row.explanation));
    }
    return item;
  }

  /**
   * The state a ranked row is in, as the backend already reported it: the status and the
   * severity as words, then the components the row reaches. Read, never compared - the words
   * are printed as they arrived.
   *
   * `options.names`, when the caller passes it, is the backend's `{component id: name}` map
   * (the Review tab's `summary.component_names`, feature 009 FR-012): each component is printed
   * by its name where it has one and by its id where it has none, and the ids stay in the
   * finding card's fold. Without it - the check tabs, which pass nothing - the components are
   * ids in the face an id is read in, exactly as before. The lookup is guarded as `stripeOf`'s
   * is, so an id that names something on `Object.prototype` prints as itself.
   */
  function attentionMeta(row, options) {
    var words = [];
    if (row.status) {
      words.push(String(row.status));
    }
    if (row.severity) {
      words.push(String(row.severity));
    }

    var names = (options && options.names) || null;
    var meta = dom.el('span', 'attention-meta', words.join(DOT));
    var components = dom.list(names ? namedComponents(row.component_ids, names) : row.component_ids);
    if (components) {
      if (meta.firstChild) {
        dom.write(meta, DOT);
      }
      meta.appendChild(dom.el('span', names ? 'attention-components' : 'attention-components mono', components));
    }
    return meta;
  }

  /** Each component id replaced by its name when the map gives it a non-blank string. */
  function namedComponents(ids, names) {
    var out = [];
    var list = ids || [];
    for (var index = 0; index < list.length; index++) {
      var id = String(list[index]);
      var name = Object.prototype.hasOwnProperty.call(names, id) ? names[id] : null;
      out.push((typeof name === 'string' && name) ? name : id);
    }
    return out;
  }

  /**
   * Which stripe a ranked row carries. `key.judgement` is the ranking's own second key and it
   * is 0 for the rows the policy says only an engineer can settle, which is the one thing about
   * a row that outranks what kind of consequence it has (contracts/attention.md section 1).
   *
   * A consequence class that is not in the map - one the policy file added, or a value that
   * happens to name something on `Object.prototype` - falls back to the quiet stripe rather
   * than to whatever the prototype chain answers with.
   */
  function stripeOf(row) {
    var key = row.key || {};
    if (key.judgement === 0) {
      return JUDGEMENT_STRIPE;
    }

    var stripe = CONSEQUENCE_STRIPE[row.consequence_class];
    return (typeof stripe === 'string') ? stripe : DEFAULT_STRIPE;
  }

  window.SwReviewAttention = {
    HEADING: HEADING,
    DOT: DOT,
    amplified: amplified,
    rowList: rowList,
    attentionRow: attentionRow,
    attentionMeta: attentionMeta,
    stripeOf: stripeOf
  };
})();
