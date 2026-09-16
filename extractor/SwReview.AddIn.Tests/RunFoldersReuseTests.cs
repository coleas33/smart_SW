using System;
using System.IO;
using SwReview.AddIn.Review;
using SwReview.Extractor.Dump;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T090. The add-in's door to the package-reuse lookup.
///
/// <see cref="RunFolders"/> is the one place that knows what a run folder is, so it is also
/// where the pane asks "is there one of these I could reuse". The index's own behaviour - a
/// missing or unparseable index is a miss, the bounded fallback scan, the folder check - is
/// tested over <see cref="PackageIndex"/> in the extractor's suite; what is asserted here is
/// that this door answers the same thing, and that the head read the step strip depends on
/// still answers after being moved behind the same reader.
/// </summary>
public sealed class RunFoldersReuseTests : IDisposable
{
    private const string Key = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

    private readonly string _root;

    public RunFoldersReuseTests()
    {
        _root = Path.Combine(Path.GetTempPath(), "SwReview.RunFoldersReuse.Tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_root);
    }

    public void Dispose()
    {
        try
        {
            Directory.Delete(_root, recursive: true);
        }
        catch (IOException)
        {
            // A temp directory that will not delete is not a test failure.
        }
    }

    [Fact]
    public void ARunFolderWithAMatchingPackage_IsFound()
    {
        WriteRun("20260912-120000-cover");

        PackageIndexRow? found = RunFolders.FindReusable(_root, Key, DumpProfile.Full);

        Assert.NotNull(found);
        Assert.Equal("20260912-120000-cover", found!.Folder);
    }

    [Fact]
    public void ARunRootWithNothingInIt_IsAMissAndNotAnError()
    {
        Assert.Null(RunFolders.FindReusable(_root, Key, DumpProfile.Full));
        Assert.Null(RunFolders.FindReusable(null, Key, DumpProfile.Full));
    }

    [Fact]
    public void AProfileThePaneDidNotAskFor_IsAMiss()
    {
        WriteRun("20260912-120000-cover");

        Assert.Null(RunFolders.FindReusable(_root, Key, DumpProfile.ModelCheck));
    }

    [Fact]
    public void TheStepStripStillReadsTheProfileOutOfTheHead()
    {
        // ProfileOf moved behind the same bounded reader the lookup uses. It is what the step
        // strip repaints from, so its answer is asserted here as well as in its own tests.
        string run = WriteRun("20260912-120000-cover");

        Assert.Equal(DumpProfile.Full, RunFolders.ProfileOf(run));
        Assert.Null(RunFolders.ProfileOf(Path.Combine(_root, "no-such-folder")));
    }

    private string WriteRun(string folder)
    {
        string directory = Path.Combine(_root, folder);
        Directory.CreateDirectory(directory);
        File.WriteAllText(
            Path.Combine(directory, PackageWriter.PackageFileName),
            "{\n"
            + "  \"schema_version\": \"1.3.0\",\n"
            + "  \"reuse_key\": \"" + Key + "\",\n"
            + "  \"extractor\": { \"name\": \"SwReview.Extractor\", \"profile\": \"full\" },\n"
            + "  \"gaps\": []\n"
            + "}\n");
        return directory;
    }
}
