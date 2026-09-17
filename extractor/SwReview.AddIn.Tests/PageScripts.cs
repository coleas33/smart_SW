using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Which scripts a page runs, in one place: its own folder, and the shared helpers under
/// `web/shared` that its own `index.html` loads.
///
/// Before feature 006 `web/shared` held one file every page loaded (`dom.js`, T080), so
/// "sweep the folder" and "what this page loads" were the same set and each page helper swept.
/// `web/shared/check-page.js` is loaded by the two check tabs and by no other page, so the two
/// answers parted company, and a page scanned against another page's script fails for message
/// types its own contract has no reason to define. The rule is written once here rather than
/// twice, so a shared file added for one page cannot quietly change what a different page's
/// contract tests scan.
/// </summary>
internal static class PageScripts
{
    /// <summary>The shared helpers, inside the mapped web folder.</summary>
    public static string SharedFolder => Path.Combine(ReviewPageFiles.WebFolder, "shared");

    /// <summary>
    /// Every script <paramref name="pageFolder"/>'s page runs, keyed by its path relative to
    /// the virtual host's root, in a stable order. A `vendor` folder is excluded as it always
    /// was: it is not this repository's code.
    /// </summary>
    /// <param name="pageFolder">The page's own folder inside the mapped web folder.</param>
    /// <param name="indexHtml">That page's `index.html`, which decides the shared half.</param>
    public static IReadOnlyList<KeyValuePair<string, string>> Collect(
        string pageFolder, string indexHtml) =>
        new[] { pageFolder, SharedFolder }
            .Where(Directory.Exists)
            .SelectMany(folder => Directory.GetFiles(folder, "*.js", SearchOption.AllDirectories))
            .Where(path => !path.Split(Path.DirectorySeparatorChar).Contains("vendor"))
            .Where(path => !IsUnder(path, SharedFolder) || Loads(indexHtml, path))
            .OrderBy(path => path, StringComparer.OrdinalIgnoreCase)
            .Select(path => new KeyValuePair<string, string>(
                path.Substring(ReviewPageFiles.WebFolder.Length)
                    .TrimStart(Path.DirectorySeparatorChar),
                File.ReadAllText(path)))
            .ToList();

    private static bool IsUnder(string path, string folder) =>
        path.StartsWith(folder + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);

    /// <summary>Whether `index.html` carries a `&lt;script src&gt;` for this shared file.</summary>
    private static bool Loads(string indexHtml, string path) =>
        indexHtml.IndexOf(
            "src=\"../../shared/" + Path.GetFileName(path) + "\"",
            StringComparison.OrdinalIgnoreCase) >= 0;
}
