using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using SwReview.Extractor.Tests;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 004's build order, lane E: the add-in's own lines of the pane side, read from its
/// source because <c>SwReviewAddIn</c> cannot be built without a live <c>ISldWorks</c>. Kept apart
/// from <see cref="ToolServiceWiringTests"/>, which lane D owns.
///
/// Two lines, each of which every host, pipeline and page test would survive losing: the one
/// pipeline the add-in builds must be handed its bind (T158), and nothing in the add-in may set
/// the Start switch (T172), which only its own commit, citing the probes' verdicts, changes.
/// </summary>
public sealed class RemodelWiringTests
{
    /// <summary>
    /// The add-in builds exactly one <c>BackendRemodelPipeline</c>, in <c>StartRemodelHost</c>, and
    /// hands it the add-in's <c>BindRemodelRun</c> as its bind, beside the remodel half of the
    /// tool service it binds for. What the bind answers is lane D's <c>BindRemodelRun</c> once the
    /// two lanes are integrated; until then the add-in's answers false, and the pipeline refuses a
    /// false bind as <c>BridgeUnavailable</c> before any open (<see cref="BackendRemodelPipelineTests"/>).
    /// </summary>
    [Fact]
    public void TheAddInsOnePipelineIsHandedItsBind()
    {
        var construction = new Regex(@"new\s+BackendRemodelPipeline\s*\(", RegexOptions.CultureInvariant);
        List<string> sites = ProductFiles()
            .SelectMany(file => construction.Matches(File.ReadAllText(file)).Cast<Match>().Select(_ => Path.GetFileName(file)))
            .ToList();
        Assert.Equal(new[] { "SwReviewAddIn.cs" }, sites);

        string host = StartRemodelHost();
        Assert.Contains(
            "Pipeline = new BackendRemodelPipeline( endpoint, () => _toolService?.RemodelBridge, BindRemodelRun,",
            host,
            StringComparison.Ordinal);

        string source = Collapsed("SwReviewAddIn.cs");
        Assert.Contains("private bool BindRemodelRun(string runDirectory)", source, StringComparison.Ordinal);
    }

    /// <summary>
    /// The Start switch is <c>RemodelStart.SeatValidated</c>, and the Remodel host and the bridge's
    /// dispatcher each take it as a constructor argument whose shipped constructor passes it (T172,
    /// as <c>DrawingOpenScope</c> takes its own): nothing in the add-in assigns a switch, and the
    /// add-in builds its one host and its one dispatcher through those shipped constructors, so a
    /// build cannot switch Start on anywhere but in the switch's own commit.
    /// </summary>
    [Fact]
    public void NothingInTheAddInSetsTheStartSwitch()
    {
        var assignment = new Regex(@"\b(SeatValidated|StartValidated|startValidated)\s*[=:](?![=>])", RegexOptions.CultureInvariant);
        List<string> assigners = ProductFiles()
            .Where(file => !file.EndsWith(Path.Combine("Remodel", "RemodelHost.cs"), StringComparison.Ordinal))
            .Where(file => assignment.IsMatch(AdapterShape.CodeOutsideComments(File.ReadAllText(file))))
            .Select(Path.GetFileName)
            .ToList();
        Assert.Empty(assigners);

        IReadOnlyList<string> host = Assert.Single(ConstructionsOf("RemodelHost"));
        Assert.Single(host);
        Assert.StartsWith("new RemodelHostOptions(", host[0], StringComparison.Ordinal);

        IReadOnlyList<string> dispatcher = Assert.Single(ConstructionsOf("SwBridgeDispatcher"));
        Assert.Equal(2, dispatcher.Count);

        Assert.Contains(
            "public RemodelHost(RemodelHostOptions options) : this(options, RemodelStart.SeatValidated)",
            Collapsed(Path.Combine("Remodel", "RemodelHost.cs")),
            StringComparison.Ordinal);
    }

    /// <summary>
    /// Every <c>new <paramref name="type"/>(...)</c> in the add-in's product code, as its top-level
    /// arguments: the text between the call's parentheses split at the commas no bracket, brace or
    /// string literal encloses.
    /// </summary>
    private static List<IReadOnlyList<string>> ConstructionsOf(string type)
    {
        var construction = new Regex(@"new\s+" + Regex.Escape(type) + @"\s*\(", RegexOptions.CultureInvariant);
        var found = new List<IReadOnlyList<string>>();
        foreach (string file in ProductFiles())
        {
            string code = AdapterShape.CodeOutsideComments(File.ReadAllText(file));
            foreach (Match match in construction.Matches(code))
            {
                found.Add(TopLevelArguments(code, match.Index + match.Length - 1));
            }
        }

        return found;
    }

    /// <summary>The top-level arguments of the call whose opening parenthesis is at <paramref name="open"/>.</summary>
    private static IReadOnlyList<string> TopLevelArguments(string code, int open)
    {
        var arguments = new List<string>();
        int depth = 0;
        int from = open + 1;
        for (int i = open; i < code.Length; i++)
        {
            char c = code[i];
            if (c == '"')
            {
                bool verbatim = i > 0 && code[i - 1] == '@';
                for (i++; i < code.Length; i++)
                {
                    if (verbatim && code[i] == '"' && i + 1 < code.Length && code[i + 1] == '"')
                    {
                        i++;
                    }
                    else if (!verbatim && code[i] == '\\')
                    {
                        i++;
                    }
                    else if (code[i] == '"')
                    {
                        break;
                    }
                }
            }
            else if (c == '(' || c == '{' || c == '[')
            {
                depth++;
            }
            else if (c == ')' || c == '}' || c == ']')
            {
                depth--;
                if (depth == 0)
                {
                    arguments.Add(code.Substring(from, i - from).Trim());
                    return arguments.Where(argument => argument.Length > 0).ToList();
                }
            }
            else if (c == ',' && depth == 1)
            {
                arguments.Add(code.Substring(from, i - from).Trim());
                from = i + 1;
            }
        }

        throw new InvalidOperationException("the call at " + open + " never closes");
    }

    private static string AddIn() =>
        Path.Combine(ErrorLabelsCoverTheHostTests.RepositoryRoot(), "extractor", "SwReview.AddIn");

    private static IEnumerable<string> ProductFiles() =>
        Directory.EnumerateFiles(AddIn(), "*.cs", SearchOption.AllDirectories)
            .Where(file => !file.Split(Path.DirectorySeparatorChar).Any(part => part == "obj" || part == "bin"));

    /// <summary>A product file with every run of white space as one space, so a pin reads past line breaks.</summary>
    private static string Collapsed(string relativePath) =>
        Regex.Replace(File.ReadAllText(Path.Combine(AddIn(), relativePath)), @"\s+", " ");

    /// <summary><c>SwReviewAddIn.StartRemodelHost</c>, up to where it starts the remodel pump.</summary>
    private static string StartRemodelHost()
    {
        string source = Collapsed("SwReviewAddIn.cs");
        int start = source.IndexOf("private void StartRemodelHost(", StringComparison.Ordinal);
        int end = start < 0 ? -1 : source.IndexOf("StartRemodelPump();", start, StringComparison.Ordinal);
        Assert.True(end > start, "SwReviewAddIn.StartRemodelHost was not found, or no longer starts the remodel pump.");
        return source.Substring(start, end - start);
    }
}
