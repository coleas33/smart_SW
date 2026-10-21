using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 009 T070: every error class the Review tab can show has a sentence in the words file
/// (FR-026, research R2.22, contracts/plain-words.md section 5).
///
/// The Python side asserts every `ChatError` subclass has a label (the py lane's T007). The
/// classes this side makes are the other half: every `SendError(id, "&lt;class&gt;"` literal in
/// the Review host and in the shared `PaneActions`, and every `ErrorPayload("&lt;class&gt;"` one - an
/// error built to be sent with more in it, as a save's `BackendNotRestarted` carries what the save says
/// of the run root (owner decision 154A, the owner's follow-up) - every refusal the Review host builds as a
/// `BackendRequestException` (owner decision 143A: the proxy answers the page's own calls with
/// them), every `PaneRunLookup`'s unknown-run class, and the three the Review page makes itself
/// (`BackendUnavailable`, `HttpError`, `HostError`). A class
/// with no sentence prints its message - correct, and exactly the developer vocabulary FR-026
/// removes - so the list is read from the source rather than kept by hand.
///
/// The sources are read from the repository, not the build output: they are C# and JavaScript
/// the add-in compiles or ships, and the words file is the backend's.
/// </summary>
public sealed class ErrorLabelsCoverTheHostTests
{
    /// <summary>
    /// The scan is not vacuous: it finds the host's refusals, the unknown-run classes of all three
    /// pane hosts, and the page's own three.
    /// </summary>
    [Fact]
    public void TheScanFindsTheClassesTheHostAndThePageMake()
    {
        ISet<string> classes = ClassesTheReviewTabCanShow();

        foreach (string expected in new[]
                 {
                     "NoDocument", "DrawingActive", "NotAttached", "BackendUnavailable", "TurnRunning", "PreparationExpired",
                     "PreparationFailed", "RunFolderFailed", "ExtractionFailed", "InvalidSettings", "UnknownModel",
                     "FakeProviderNotAllowed", "InvalidRequest", "UnknownMessage", "HostError", "PathRefused",
                     "NotFound", "OpenFailed", "UnknownChat", "UnknownCheck", "HttpError", "SettingNotSaved", "ReviewNotActive",
                     "RemodelRunning", "DocumentChanged", "BackendNotRestarted", "BridgeOnAnotherDocument",
                     "RunRootRefused", "RunRootChanged", "RunRootNotFullPath", "RunRootChosenNotInForce",
                     "CheckRunning",
                 })
        {
            Assert.Contains(expected, classes);
        }
    }

    /// <summary>
    /// Every one of them is a key of the words file's `labels.errors`. The words file is the py
    /// lane's T008 (`reviewer/src/swreview/report/review_words_v1.yaml`).
    /// </summary>
    [Fact]
    public void EveryClassTheReviewTabCanShowHasASentenceInTheWordsFile()
    {
        string words = Path.Combine(RepositoryRoot(), "reviewer", "src", "swreview", "report", "review_words_v1.yaml");
        Assert.True(File.Exists(words), words + " is missing.");

        ISet<string> labelled = ErrorKeys(File.ReadAllLines(words));
        string[] missing = ClassesTheReviewTabCanShow().Where(name => !labelled.Contains(name)).OrderBy(name => name, StringComparer.Ordinal).ToArray();

        Assert.True(
            missing.Length == 0,
            "These error classes have no sentence under labels.errors in review_words_v1.yaml: " + string.Join(", ", missing));
    }

    // ---- reading the sources ---------------------------------------------------------------------

    private static readonly Regex SendErrorLiteral = new Regex(
        @"(?:SendError\(\s*id\s*,|ErrorPayload\()\s*""([A-Za-z]+)""", RegexOptions.Compiled);

    /// <summary>
    /// A refusal the Review host builds as an exception: sent on by `Receive`, or answered to the
    /// page's own backend call by the pane's proxy (owner decision 143A, `PageTurnRefusal`).
    /// </summary>
    private static readonly Regex HostRefusalLiteral = new Regex(
        @"new\s+BackendRequestException\(\s*""([A-Za-z]+)""", RegexOptions.Compiled);

    private static readonly Regex UnknownRunClass = new Regex(
        @"new\s+PaneRunLookup\(\s*""[a-z_]+""\s*,\s*""([A-Za-z]+)""", RegexOptions.Compiled);

    private static readonly Regex PageClass = new Regex(@"'([A-Z][A-Za-z]+(?:Error|Unavailable))'", RegexOptions.Compiled);

    private static ISet<string> ClassesTheReviewTabCanShow()
    {
        string addIn = Path.Combine(RepositoryRoot(), "extractor", "SwReview.AddIn");
        var classes = new HashSet<string>(StringComparer.Ordinal);

        foreach (string host in new[] { Path.Combine(addIn, "Review", "ReviewHost.cs"), Path.Combine(addIn, "Review", "PaneActions.cs") })
        {
            foreach (Match match in SendErrorLiteral.Matches(File.ReadAllText(host)))
            {
                classes.Add(match.Groups[1].Value);
            }
        }

        foreach (Match match in HostRefusalLiteral.Matches(File.ReadAllText(Path.Combine(addIn, "Review", "ReviewHost.cs"))))
        {
            classes.Add(match.Groups[1].Value);
        }

        foreach (string source in Directory.GetFiles(addIn, "*.cs", SearchOption.AllDirectories))
        {
            foreach (Match match in UnknownRunClass.Matches(File.ReadAllText(source)))
            {
                classes.Add(match.Groups[1].Value);
            }
        }

        foreach (Match match in PageClass.Matches(File.ReadAllText(Path.Combine(addIn, "Review", "ReviewPage", "app.js"))))
        {
            classes.Add(match.Groups[1].Value);
        }

        return classes;
    }

    /// <summary>The keys of `labels.errors`, read by indentation: the words file is YAML and this side has no parser.</summary>
    private static ISet<string> ErrorKeys(string[] lines)
    {
        var keys = new HashSet<string>(StringComparer.Ordinal);
        int labels = Array.FindIndex(lines, line => Regex.IsMatch(line, @"^labels:\s*$"));
        Assert.True(labels >= 0, "review_words_v1.yaml has no top-level labels block.");

        int errors = Array.FindIndex(lines, labels, line => Regex.IsMatch(line, @"^\s+errors:\s*$"));
        Assert.True(errors >= 0, "review_words_v1.yaml has no labels.errors block.");

        int indent = lines[errors].Length - lines[errors].TrimStart().Length;
        for (int index = errors + 1; index < lines.Length; index++)
        {
            string line = lines[index];
            if (line.Trim().Length == 0 || line.TrimStart().StartsWith("#", StringComparison.Ordinal))
            {
                continue;
            }

            int depth = line.Length - line.TrimStart().Length;
            if (depth <= indent)
            {
                break;
            }

            Match key = Regex.Match(line, @"^\s+([A-Za-z]+):");
            if (key.Success)
            {
                keys.Add(key.Groups[1].Value);
            }
        }

        return keys;
    }

    /// <summary>The repository's root: the first folder above the test assembly that holds both `extractor` and `specs`.</summary>
    internal static string RepositoryRoot()
    {
        for (DirectoryInfo? folder = new DirectoryInfo(AppContext.BaseDirectory); folder != null; folder = folder.Parent)
        {
            if (Directory.Exists(Path.Combine(folder.FullName, "extractor")) && Directory.Exists(Path.Combine(folder.FullName, "specs")))
            {
                return folder.FullName;
            }
        }

        throw new InvalidOperationException("the repository root was not found above " + AppContext.BaseDirectory);
    }
}
