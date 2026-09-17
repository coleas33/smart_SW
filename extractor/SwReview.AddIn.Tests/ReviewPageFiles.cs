using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Where the Review page's vendored files and the contracts that govern them live, for the
/// two tests that read them: T042 scans the page scripts against
/// `contracts/pane-host-messages.md`, and T042a loads the page in an offscreen WebView2.
///
/// Everything is read from the build output rather than from the source tree, for two reasons.
/// The output is the copy the add-in actually ships - the `&lt;Content&gt;` items in
/// SwReview.AddIn.csproj land the page under `web/`, which is the folder
/// <see cref="SwReview.AddIn.Review.PageFileServer"/> serves `https://swreview.invalid` from -
/// so a page file that never reaches `web/` fails the scan instead of passing it from source. And it is the same
/// convention <see cref="SettingsContract"/> already uses for a copied contract file, so there
/// is one way to find a contract in this assembly rather than two.
/// </summary>
internal static class ReviewPageFiles
{
    /// <summary>The folder the add-in serves as `https://swreview.invalid`.</summary>
    public static string WebFolder => Path.Combine(AppContext.BaseDirectory, "web");

    /// <summary>The Review page's own folder inside it.</summary>
    public static string Folder => Path.Combine(WebFolder, "Review", "ReviewPage");

    /// <summary>The URL the add-in navigates the Review tab to (pane-host-messages.md).</summary>
    public const string PageUrl = "https://swreview.invalid/Review/ReviewPage/index.html";

    /// <summary>`index.html` as shipped.</summary>
    public static string IndexHtml() => Read("index.html");

    /// <summary>
    /// Every script the page ships, by file name. `vendor/` is excluded: third-party files are
    /// not ours to hold to the page's rules, and the Review page has none today.
    /// </summary>
    public static IReadOnlyList<KeyValuePair<string, string>> Scripts()
    {
        AssertPresent();

        List<KeyValuePair<string, string>> scripts = Directory
            .GetFiles(Folder, "*.js", SearchOption.AllDirectories)
            .Where(path => !path.Split(Path.DirectorySeparatorChar).Contains("vendor"))
            .OrderBy(path => path, StringComparer.OrdinalIgnoreCase)
            .Select(path => new KeyValuePair<string, string>(
                GetRelativeName(path),
                File.ReadAllText(path)))
            .ToList();

        Assert.True(
            scripts.Count > 0,
            $"No page scripts were found under {Folder}; check the Content items in SwReview.AddIn.csproj.");
        return scripts;
    }

    /// <summary>One page file, by name relative to <see cref="Folder"/>.</summary>
    public static string Read(string name)
    {
        AssertPresent();
        string path = Path.Combine(Folder, name);
        Assert.True(File.Exists(path), $"{name} is missing from {Folder}.");
        return File.ReadAllText(path);
    }

    /// <summary>Whether the page ships a file with this name (T042a reports its absence itself).</summary>
    public static bool Exists(string name) => File.Exists(Path.Combine(Folder, name));

    /// <summary>A contract file copied next to the test assembly by the csproj.</summary>
    public static string ReadContract(string fileName)
    {
        string path = Path.Combine(AppContext.BaseDirectory, fileName);
        Assert.True(
            File.Exists(path),
            $"{fileName} was not copied next to the test assembly; check the Content item in the csproj.");
        return File.ReadAllText(path);
    }

    private static string GetRelativeName(string path) =>
        path.Substring(Folder.Length).TrimStart(Path.DirectorySeparatorChar);

    private static void AssertPresent() =>
        Assert.True(
            Directory.Exists(Folder),
            $"The Review page was not copied to {Folder}; check the Content items in SwReview.AddIn.csproj.");
}
