using System;
using System.IO;
using SwReview.AddIn.Review;
using SwReview.Extractor.Ir;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T040: the two id lookups Show in SOLIDWORKS needs, read out of the run's own `package.json`.
///
/// A finding names entities the way the package names them - `persist_ref_scope` is a
/// `document_id` and the affected component is a `component_id` - and SOLIDWORKS knows neither.
/// It wants the document's path, so a reference belonging to a part is resolved against that
/// part rather than against the assembly, and the component's full instance path, which is both
/// what `SelectByID2` addresses a component by and what a failed resolve hands back so the
/// engineer can find the component in the tree (spec Edge Cases, SC-007).
///
/// Nothing here throws. A lookup that cannot be answered is answered `null`: Show then falls
/// back to selecting the resolved entity by type and reports no full path, which is a worse
/// answer than the right one and a much better one than an exception out of the application
/// thread while SOLIDWORKS is waiting on it.
/// </summary>
public sealed class RunPackageIndexTests : IDisposable
{
    private readonly string _root;

    public RunPackageIndexTests()
    {
        _root = Path.Combine(Path.GetTempPath(), "SwReview.RunPackage.Tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_root);
    }

    [Fact]
    public void ADocumentIdNamesTheDocumentsPath()
    {
        string run = WriteRun("run-1");
        var index = new RunPackageIndex(() => run);

        Assert.Equal(@"C:\parts\bracket.sldprt", index.DocumentPath("doc-2"));
    }

    [Fact]
    public void AComponentIdNamesTheComponentsFullInstancePath()
    {
        string run = WriteRun("run-1");
        var index = new RunPackageIndex(() => run);

        Assert.Equal("bracket-1", index.ComponentFullPath("cmp-1"));
    }

    [Fact]
    public void AnIdThatIsNotInThePackageIsAnsweredNull()
    {
        string run = WriteRun("run-1");
        var index = new RunPackageIndex(() => run);

        Assert.Null(index.DocumentPath("doc-99"));
        Assert.Null(index.ComponentFullPath("cmp-99"));
        Assert.Null(index.DocumentPath(string.Empty));
        Assert.Null(index.ComponentFullPath(null!));
    }

    [Fact]
    public void BeforeTheFirstReviewThereIsNoRunAndNothingThrows()
    {
        var index = new RunPackageIndex(() => null);

        Assert.Null(index.DocumentPath("doc-2"));
        Assert.Null(index.ComponentFullPath("cmp-1"));
    }

    [Fact]
    public void ARunWhosePackageIsMissingOrUnreadableAnswersNullRatherThanThrowing()
    {
        string missing = Path.Combine(_root, "run-empty");
        Directory.CreateDirectory(missing);

        var index = new RunPackageIndex(() => missing);
        Assert.Null(index.ComponentFullPath("cmp-1"));

        // A dump that stopped halfway leaves a file that is not a package. Show must still
        // answer the page (constitution Principle I), and it must not answer with an exception.
        File.WriteAllText(Path.Combine(missing, "package.json"), "{ \"schema_version\": ");
        var broken = new RunPackageIndex(() => missing);
        Assert.Null(broken.ComponentFullPath("cmp-1"));
    }

    /// <summary>
    /// The pane follows the engineer: a second review replaces the first, and the ids on the
    /// cards then belong to the second run's package. An index that kept the first one would
    /// select the wrong component rather than none, which is the worse of the two failures.
    /// </summary>
    [Fact]
    public void TheIndexFollowsTheRunItIsAskedAbout()
    {
        string first = WriteRun("run-1");
        string second = WriteRun("run-2", componentFullPath: "housing-4");

        string current = first;
        var index = new RunPackageIndex(() => current);

        Assert.Equal("bracket-1", index.ComponentFullPath("cmp-1"));

        current = second;
        Assert.Equal("housing-4", index.ComponentFullPath("cmp-1"));
    }

    /// <summary>
    /// The package is read once per run, not once per Show. A review of a large assembly writes
    /// a package of tens of megabytes and a finding card's Show is pressed repeatedly; re-reading
    /// and re-parsing it on the application thread every time would stall SOLIDWORKS for the
    /// engineer who is using the feature most.
    /// </summary>
    [Fact]
    public void ThePackageIsReadOncePerRun()
    {
        string run = WriteRun("run-1");
        var index = new RunPackageIndex(() => run);

        Assert.Equal("bracket-1", index.ComponentFullPath("cmp-1"));

        File.Delete(Path.Combine(run, "package.json"));

        Assert.Equal("bracket-1", index.ComponentFullPath("cmp-1"));
        Assert.Equal(@"C:\parts\bracket.sldprt", index.DocumentPath("doc-2"));
    }

    /// <summary>
    /// T134g: a remodel run folder holds no `package.json`, and it is a folder Show is asked
    /// about.
    ///
    /// The add-in's before-dump is written by the extractor under its own name and then renamed
    /// to `package-before.json` (`contracts/run-artifacts.md` rows 27-28), so the folder a
    /// `remodel.plan` creates never holds the name this index was written to read. That folder
    /// is also what the remodel host registers as the pane's latest run through
    /// `ReviewHost.TrackCheck`, and the latest run is the folder
    /// <see cref="SwEntityResolver"/> resolves every `document_id` through - so without this
    /// fallback, pressing Remodel would silently degrade Show to "no full path" on the Review
    /// and Model check tabs for as long as the remodel stayed the latest run.
    /// </summary>
    [Fact]
    public void ARemodelRunResolvesIdsThroughItsBeforeDump()
    {
        string run = WriteRun("run-remodel", packageName: "package-before.json");

        var index = new RunPackageIndex(() => run);

        Assert.Equal(@"C:\parts\bracket.sldprt", index.DocumentPath("doc-2"));
        Assert.Equal("bracket-1", index.ComponentFullPath("cmp-1"));
    }

    /// <summary>
    /// A review's own package is the reading of the folder, and a run folder that somehow holds
    /// both names is read through it rather than through the remodel fallback: the order is
    /// fixed rather than "whichever is newer", because Show must resolve the same way on every
    /// press.
    /// </summary>
    [Fact]
    public void AFolderHoldingBothPackagesIsReadThroughTheReviewsOwnPackage()
    {
        string run = WriteRun("run-both");
        WriteInto(run, "package-before.json", "housing-4");

        var index = new RunPackageIndex(() => run);

        Assert.Equal("bracket-1", index.ComponentFullPath("cmp-1"));
    }

    /// <summary>
    /// A `package.json` that cannot be parsed - a dump killed halfway, a build that cannot read
    /// that schema - is not the end of the search. The next name is tried, because the folder
    /// may still hold a package that answers, and an id answered is better than an id not
    /// answered (constitution Principle I: unknown stays unknown only when it really is).
    /// </summary>
    [Fact]
    public void AnUnreadablePackageFallsThroughToTheNextName()
    {
        string run = WriteRun("run-broken", packageName: "package-before.json");
        File.WriteAllText(Path.Combine(run, "package.json"), "{ \"schema_version\": ");

        var index = new RunPackageIndex(() => run);

        Assert.Equal("bracket-1", index.ComponentFullPath("cmp-1"));
    }

    private string WriteRun(
        string name,
        string componentFullPath = "bracket-1",
        string packageName = "package.json")
    {
        string run = Path.Combine(_root, name);
        Directory.CreateDirectory(run);
        WriteInto(run, packageName, componentFullPath);
        return run;
    }

    /// <summary>One package, under one of the names a run folder can hold it under.</summary>
    private static void WriteInto(string run, string packageName, string componentFullPath)
    {
        var package = new EvidencePackage();
        package.Documents.Add(new Document
        {
            DocumentId = "doc-1",
            Kind = DocumentKind.Assembly,
            FileName = "top.sldasm",
            Path = @"C:\parts\top.sldasm",
            ActiveConfiguration = "Default",
        });
        package.Documents.Add(new Document
        {
            DocumentId = "doc-2",
            Kind = DocumentKind.Part,
            FileName = "bracket.sldprt",
            Path = @"C:\parts\bracket.sldprt",
            ActiveConfiguration = "Default",
        });
        package.Components.Add(new ComponentInstance
        {
            Id = "cmp-1",
            PersistRef = "AQAAAA==",
            PersistRefScope = "doc-1",
            Name = "bracket",
            FullPath = componentFullPath,
            DocumentId = "doc-2",
            ReferencedConfiguration = "Default",
        });

        File.WriteAllText(Path.Combine(run, packageName), PackageSerializer.Serialize(package));
    }

    public void Dispose()
    {
        try
        {
            Directory.Delete(_root, recursive: true);
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }
}
