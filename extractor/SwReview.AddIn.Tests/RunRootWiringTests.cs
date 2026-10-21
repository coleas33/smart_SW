using System;
using System.IO;
using System.Text.RegularExpressions;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// The owner's follow-up to decision 154A (feature 002 T194): the run root in force is the one the running
/// backend was started with - the review host's <c>RunRoot</c> - and every tab makes and finds its run folders
/// under it. The backend refuses a run folder outside the run root it was started with, and finds a check or a
/// review by name under it, so a tab that read the settings saved would, between a save and the restart that
/// brings its run root in, make a check's folder the backend refuses and look for the newest check where the
/// backend does not. The add-in builds the Model check, Standards and Remodel hosts with one named reading of
/// the review host's run root; the add-in itself cannot run outside SOLIDWORKS, so its source is read, as
/// <c>RemodelWiringTests</c> reads it.
/// </summary>
public sealed class RunRootWiringTests
{
    [Theory]
    [InlineData("ModelCheckHostOptions", "ModelCheckChannel")]
    [InlineData("StandardsHostOptions", "StandardsChannel")]
    [InlineData("RemodelHostOptions", "RemodelChannel")]
    public void EveryOtherTabTakesTheRunRootInForce(string options, string channel)
    {
        Assert.Contains(
            "new " + options + "( _pane." + channel + ", RunRootInForce)",
            Collapsed("SwReviewAddIn.cs"),
            StringComparison.Ordinal);
    }

    /// <summary>
    /// The reviews' finding F6: each of the three is handed every run root in force this session, the review
    /// host's, so a run made under one a save has since moved still opens there, and the Remodel tab still
    /// knows its copies.
    /// </summary>
    [Fact]
    public void EveryOtherTabIsHandedEveryRunRootInForce()
    {
        string source = Collapsed("SwReviewAddIn.cs");

        Assert.Equal(3, source.Split(new[] { "RunRootsInForce = RunRootsInForce," }, StringSplitOptions.None).Length - 1);
        Assert.Contains(
            "private IReadOnlyList<string> RunRootsInForce() => _reviewHost?.RunRootsInForce ?? new[] { RunRootInForce() };",
            source,
            StringComparison.Ordinal);
    }

    /// <summary>
    /// Owner decision 154A, with 153A's record of the settings in force (feature 002 T201): each of the three makes
    /// a new run's folder under the review host's run root for a new run - none while a start of the backend under
    /// way would bring another run root into force - and under the default run root only when there is no review
    /// host, as the add-in unloads. One reading of the host: one that answered none and was then read as the
    /// default would make the run the start was refused for.
    /// </summary>
    [Fact]
    public void EveryOtherTabTakesTheRunRootForANewRunFromTheReviewHost()
    {
        string source = Collapsed("SwReviewAddIn.cs");

        Assert.Equal(3, source.Split(new[] { "RunRootForANewRun = RunRootForANewRun," }, StringSplitOptions.None).Length - 1);
        Assert.Contains(
            "private string? RunRootForANewRun() { ReviewHost? host = _reviewHost; "
            + "return host == null ? RunRootInForce() : host.RunRootForANewRun(); }",
            source,
            StringComparison.Ordinal);
    }

    /// <summary>
    /// The reviews of 154A's merge, N4 (feature 002 T204): each of the three is handed the run root saved in the
    /// review host's Settings, so a start refused for the run root in force while another folder is chosen and not in
    /// force says to retry the restart, not to choose a folder again.
    /// </summary>
    [Fact]
    public void EveryOtherTabIsHandedTheRunRootSaved()
    {
        string source = Collapsed("SwReviewAddIn.cs");

        Assert.Equal(3, source.Split(new[] { "RunRootSaved = RunRootSaved," }, StringSplitOptions.None).Length - 1);
        Assert.Contains("private string? RunRootSaved() => _reviewHost?.Settings.RunRoot;", source, StringComparison.Ordinal);
    }

    [Fact]
    public void TheRunRootInForceIsTheReviewHosts()
    {
        Assert.Contains(
            "private string RunRootInForce() => _reviewHost?.RunRoot ?? UserSettings.DefaultRunRoot();",
            Collapsed("SwReviewAddIn.cs"),
            StringComparison.Ordinal);
    }

    [Fact]
    public void NoTabTakesItsRunRootFromTheSettingsSaved()
    {
        Assert.DoesNotContain("Settings ?? UserSettings.Defaults()).RunRoot", Collapsed("SwReviewAddIn.cs"), StringComparison.Ordinal);
    }

    /// <summary>A product file with every run of white space as one space, so a pin reads past line breaks.</summary>
    private static string Collapsed(string relativePath) =>
        Regex.Replace(
            File.ReadAllText(Path.Combine(ErrorLabelsCoverTheHostTests.RepositoryRoot(), "extractor", "SwReview.AddIn", relativePath)),
            @"\s+",
            " ");
}
