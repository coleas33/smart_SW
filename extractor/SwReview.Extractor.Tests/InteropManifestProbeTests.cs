using System;
using System.IO;
using System.Text;
using SwReview.Extractor.Console;
using SwReview.Extractor.Rms;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// 004 T181 (default taken 2026-09-27, the owner may revise; research R15.1):
/// <c>swreview-extract probe interop --emit-manifest &lt;path&gt; [--force]</c> - its options, its
/// refusals (each writing nothing), and a run over the test host's folder, which holds a copy of
/// both interop assemblies (the test project references them with <c>Private=true</c>), so it is
/// a redist folder on any machine that built this. No SOLIDWORKS is attached to or started, and
/// <see cref="RemodelInteropManifestGenerationTests"/> pins that the command's code cannot.
/// </summary>
public sealed class InteropManifestProbeTests : IDisposable
{
    private static readonly DateTime At = new DateTime(2026, 9, 27, 8, 9, 10, DateTimeKind.Utc);

    private readonly string _root = Path.Combine(Path.GetTempPath(), "swreview-interop-probe-" + Guid.NewGuid().ToString("N"));
    private readonly StringWriter _output = new StringWriter();
    private readonly StringWriter _error = new StringWriter();

    public InteropManifestProbeTests()
    {
        Directory.CreateDirectory(_root);
    }

    /// <summary>
    /// Best effort: an assembly the command loaded stays locked until the test host exits, so a
    /// folder holding one is left in the temporary folder rather than failing the test that made it.
    /// </summary>
    public void Dispose()
    {
        _output.Dispose();
        _error.Dispose();
        try
        {
            if (Directory.Exists(_root))
            {
                Directory.Delete(_root, recursive: true);
            }
        }
        catch (Exception failure) when (failure is UnauthorizedAccessException || failure is IOException)
        {
        }
    }

    private static string Redist => AppContext.BaseDirectory;

    // ---- the options ---------------------------------------------------------------------------

    [Fact]
    public void InteropIsTheFifthSubjectOfProbe()
    {
        Assert.Contains("interop", Program.ProbeSubjects);
        Assert.Equal(new[] { "emit-manifest", "force" }, Program.InteropProbeOptionNames);
    }

    [Fact]
    public void ThePathAndTheForceFlagAreRead()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "probe", "interop", "--emit-manifest", @"C:\out\manifest.json", "--force" },
            2,
            Program.InteropProbeOptionNames);

        Assert.Equal(@"C:\out\manifest.json", parsed.Value("emit-manifest"));
        Assert.True(parsed.Flag("force"));
    }

    [Fact]
    public void WithoutTheFlagTheCommandDoesNotForce()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "probe", "interop", "--emit-manifest", "manifest.json" }, 2, Program.InteropProbeOptionNames);

        Assert.False(parsed.Flag("force"));
    }

    /// <summary>
    /// It addresses no document and no session: <c>--allow-start</c> would promise something about
    /// a session it never asks for, and <c>--doc</c> a document it never reads, so both are errors.
    /// </summary>
    [Theory]
    [InlineData("--allow-start")]
    [InlineData("--doc")]
    [InlineData("--out")]
    public void AnOptionAboutADocumentOrASessionIsAUsageError(string option)
    {
        Assert.Throws<UsageError>(() => CommandLine.Parse(
            new[] { "probe", "interop", "--emit-manifest", "manifest.json", option }, 2, Program.InteropProbeOptionNames));

        Assert.Equal(1, Program.RunProbe(new[] { "probe", "interop", "--emit-manifest", Path.Combine(_root, "m.json"), option }));
        Assert.False(File.Exists(Path.Combine(_root, "m.json")));
    }

    [Fact]
    public void ProbeInteropWithNoPathExitsOneAndWritesNothing()
    {
        Assert.Equal(1, Program.RunProbe(new[] { "probe", "interop" }));
        Assert.Empty(Directory.GetFileSystemEntries(_root));
    }

    // ---- the refusals, each writing nothing ------------------------------------------------------

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public void APathIsRequired(string? path)
    {
        Assert.Equal(1, Run(path));
        Assert.Contains("--emit-manifest <path> names the file to write, and is required.", _error.ToString(), StringComparison.Ordinal);
        Assert.Empty(_output.ToString());
    }

    [Fact]
    public void AFolderIsNotAFile()
    {
        Assert.Equal(1, Run(_root));
        Assert.Contains("is a folder", _error.ToString(), StringComparison.Ordinal);
        Assert.Empty(Directory.GetFileSystemEntries(_root));
    }

    [Fact]
    public void AnExistingFileIsLeftAsItIsWithoutForce()
    {
        string path = Path.Combine(_root, "manifest.json");
        File.WriteAllText(path, "the reviewed manifest");

        Assert.Equal(1, Run(path));

        Assert.Equal("the reviewed manifest", File.ReadAllText(path));
        Assert.Contains("already exists and was left as it is", _error.ToString(), StringComparison.Ordinal);
        Assert.Contains("--force", _error.ToString(), StringComparison.Ordinal);
    }

    [Fact]
    public void NoRedistFolderIsSaidAndNothingIsWritten()
    {
        string path = Path.Combine(_root, "manifest.json");

        Assert.Equal(1, InteropManifestProbe.Run(path, false, null, At, _output, _error));

        Assert.False(File.Exists(path));
        Assert.Contains("no api\\redist folder was found", _error.ToString(), StringComparison.Ordinal);
        Assert.Contains("SWREVIEW_SW_REDIST", _error.ToString(), StringComparison.Ordinal);
    }

    [Fact]
    public void ARedistFolderWithoutTheAssembliesIsNamedAndNothingIsWritten()
    {
        string path = Path.Combine(_root, "manifest.json");
        string empty = Path.Combine(_root, "redist");
        Directory.CreateDirectory(empty);

        Assert.Equal(1, InteropManifestProbe.Run(path, false, empty, At, _output, _error));

        Assert.False(File.Exists(path));
        Assert.Contains("looked in " + empty, _error.ToString(), StringComparison.Ordinal);
    }

    [Fact]
    public void AnAssemblyThatWillNotLoadIsSaidAndNothingIsWritten()
    {
        string path = Path.Combine(_root, "manifest.json");
        string broken = Path.Combine(_root, "broken");
        Directory.CreateDirectory(broken);
        File.WriteAllText(Path.Combine(broken, "SolidWorks.Interop.sldworks.dll"), "not an assembly");
        File.WriteAllText(Path.Combine(broken, "SolidWorks.Interop.swconst.dll"), "not an assembly");

        Assert.Equal(1, InteropManifestProbe.Run(path, false, broken, At, _output, _error));

        Assert.False(File.Exists(path));
        Assert.Contains("could not be read: BadImageFormatException", _error.ToString(), StringComparison.Ordinal);
    }

    /// <summary>
    /// Assemblies that are not the interop the code records - here two copies of xUnit's own - read
    /// cleanly and answer none of the rows: every one is a problem, each is printed, and the file
    /// is not written, so a manifest can never record a surface nobody has.
    /// </summary>
    [Fact]
    public void AnInstalledAssemblyThatDiffersIsEveryProblemPrintedAndNothingWritten()
    {
        string path = Path.Combine(_root, "manifest.json");
        string other = Path.Combine(_root, "other");
        Directory.CreateDirectory(other);
        string stranger = typeof(FactAttribute).Assembly.Location;
        File.Copy(stranger, Path.Combine(other, "SolidWorks.Interop.sldworks.dll"));
        File.Copy(stranger, Path.Combine(other, "SolidWorks.Interop.swconst.dll"));

        Assert.Equal(1, InteropManifestProbe.Run(path, false, other, At, _output, _error));

        Assert.False(File.Exists(path));
        string said = _error.ToString();
        Assert.Contains("nothing was written", said, StringComparison.Ordinal);
        Assert.Contains("IModelDocExtension is gone", said, StringComparison.Ordinal);
        Assert.Contains("swOpenDocOptions_e is gone", said, StringComparison.Ordinal);
        Assert.Contains("IEquationMgr is gone, so its recorded absence cannot be checked", said, StringComparison.Ordinal);
        Assert.Empty(_output.ToString());
    }

    // ---- a run ---------------------------------------------------------------------------------

    [Fact]
    public void ARunWritesWhatTheGeneratorWritesAndSaysWhatItRead()
    {
        string path = Path.Combine(_root, "nested", "folder", "manifest.json");

        Assert.Equal(0, Run(path));

        RemodelInteropGeneration expected = RemodelInteropManifest.Generate(RemodelInteropAssemblies.FromRedist(Redist)!, At);
        byte[] bytes = File.ReadAllBytes(path);
        Assert.False(bytes.Length >= 3 && bytes[0] == 0xEF && bytes[1] == 0xBB && bytes[2] == 0xBF, "the manifest carries a byte-order mark");
        Assert.Equal(RemodelInteropManifest.Write(expected.Document), Encoding.UTF8.GetString(bytes));
        Assert.Contains("\"generated_at\": \"2026-09-27T08:09:10Z\"", File.ReadAllText(path), StringComparison.Ordinal);

        string said = _output.ToString();
        Assert.StartsWith("wrote " + path + ": ", said, StringComparison.Ordinal);
        Assert.Contains(expected.Document.Members.Count + " members", said, StringComparison.Ordinal);
        Assert.Contains(" absences, from SolidWorks.Interop.sldworks " + expected.Document.AssemblyVersion, said, StringComparison.Ordinal);
        Assert.Contains("(" + expected.Document.Product + ") in " + Redist, said, StringComparison.Ordinal);
        Assert.Empty(_error.ToString());
    }

    [Fact]
    public void ForceWritesOverAnExistingFile()
    {
        string path = Path.Combine(_root, "manifest.json");
        File.WriteAllText(path, "the old manifest");

        Assert.Equal(0, InteropManifestProbe.Run(path, true, Redist, At, _output, _error));

        Assert.StartsWith("{\n  \"manifest_schema\": \"1.0\",", File.ReadAllText(path), StringComparison.Ordinal);
    }

    private int Run(string? path) => InteropManifestProbe.Run(path, false, Redist, At, _output, _error);
}
