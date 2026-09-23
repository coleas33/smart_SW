/*
  Which document a result belongs to, for every page that binds one (U8).

  The Review tab binds a review to the document `review.started` named, and the two check tabs
  bind a check result to the document it graded. When `document.changed` names another one, each
  hides what it was showing and says whose it is (docs/pane-findings-2026-09-20-review-gui.md
  section 1). "Is this the same document" is one rule, so it is written once, here, rather than
  once per page: a second copy of it is the copy that disagrees about case or configuration the
  first time either is touched, and then one tab hides a result the other one shows.

  The rule:

  - the path is compared ignoring case, because Windows opens `C:\PARTS\A.SLDPRT` and
    `c:\parts\a.sldprt` as one file;
  - the configuration is compared exactly, because a review of one configuration is not a
    review of another (suppression, mates and interference are all per configuration), and the
    host compares it exactly too (ReviewHost's preparation check);
  - no document, or a document with no path, on either side is never the same document.

  Nothing here touches the DOM, the host bridge or the network: these are string functions,
  and `dom.js` stays the one place a string becomes a text node.
*/

(function () {
  'use strict';

  /** The last segment of a Windows or POSIX path; the pages show names, not paths. */
  function fileName(path) {
    var text = String(path || '');
    var cut = Math.max(text.lastIndexOf('\\'), text.lastIndexOf('/'));
    return cut >= 0 ? text.substring(cut + 1) : text;
  }

  /** `bracket.sldasm [Default]`: the file and its configuration, or '' for no document. */
  function label(info) {
    if (!info || !info.path) {
      return '';
    }
    return fileName(info.path) + (info.configuration ? ' [' + info.configuration + ']' : '');
  }

  /** Whether two `{path, configuration}` values name the same document, by the rule above. */
  function same(left, right) {
    if (!left || !right || !left.path || !right.path) {
      return false;
    }
    return String(left.path).toLowerCase() === String(right.path).toLowerCase()
      && configurationOf(left) === configurationOf(right);
  }

  /** An absent configuration and an empty one are the same absence. */
  function configurationOf(info) {
    return info.configuration ? String(info.configuration) : '';
  }

  window.SwReviewDocument = {
    fileName: fileName,
    label: label,
    same: same
  };
})();
