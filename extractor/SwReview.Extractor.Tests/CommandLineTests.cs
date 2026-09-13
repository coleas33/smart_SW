using System;
using SwReview.Extractor.Console;
using SwReview.Extractor.Dump;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T059's argument parsing. A typo in <c>--meshes none</c> must not quietly write meshes,
/// and an unknown option must not be ignored, so both are errors.
/// </summary>
public class CommandLineTests
{
    private static readonly string[] DumpOptions = { "doc", "config", "out", "meshes", "faces" };

    [Fact]
    public void Parse_ReadsNameValuePairs()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "dump", "--out", @"C:\out", "--config", "Default" }, 1, DumpOptions);

        Assert.Equal(@"C:\out", parsed.Value("out"));
        Assert.Equal("Default", parsed.Value("config"));
    }

    [Fact]
    public void Parse_MissingOption_IsNull()
    {
        CommandLine parsed = CommandLine.Parse(new[] { "dump", "--out", @"C:\out" }, 1, DumpOptions);

        Assert.Null(parsed.Value("doc"));
    }

    [Fact]
    public void Parse_OptionNamesAreCaseInsensitive()
    {
        CommandLine parsed = CommandLine.Parse(new[] { "dump", "--OUT", @"C:\out" }, 1, DumpOptions);

        Assert.Equal(@"C:\out", parsed.Value("out"));
    }

    [Fact]
    public void Parse_UnknownOption_Throws()
    {
        UsageError error = Assert.Throws<UsageError>(() =>
            CommandLine.Parse(new[] { "dump", "--mesh", "none" }, 1, DumpOptions));

        Assert.Contains("--mesh", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Parse_BareArgument_Throws()
    {
        Assert.Throws<UsageError>(() =>
            CommandLine.Parse(new[] { "dump", @"C:\out" }, 1, DumpOptions));
    }

    [Fact]
    public void Parse_FlagWithoutValue_IsNull()
    {
        CommandLine parsed = CommandLine.Parse(
            new[] { "dump", "--faces", "--out", @"C:\out" }, 1, DumpOptions);

        Assert.Null(parsed.Value("faces"));
        Assert.Equal(@"C:\out", parsed.Value("out"));
    }

    [Fact]
    public void Required_MissingOption_Throws()
    {
        CommandLine parsed = CommandLine.Parse(new[] { "dump" }, 1, DumpOptions);

        Assert.Throws<UsageError>(() => parsed.Required("out"));
    }

    [Fact]
    public void Required_BlankValue_Throws()
    {
        CommandLine parsed = CommandLine.Parse(new[] { "dump", "--out", "   " }, 1, DumpOptions);

        Assert.Throws<UsageError>(() => parsed.Required("out"));
    }

    [Theory]
    [InlineData("glb", MeshFormat.Glb)]
    [InlineData("GLB", MeshFormat.Glb)]
    [InlineData("stl", MeshFormat.Stl)]
    [InlineData("none", MeshFormat.None)]
    public void MeshFormat_ReadsTheOption(string value, MeshFormat expected)
    {
        CommandLine parsed = CommandLine.Parse(new[] { "dump", "--meshes", value }, 1, DumpOptions);

        Assert.Equal(expected, parsed.MeshFormat());
    }

    [Fact]
    public void MeshFormat_DefaultsToGlb()
    {
        Assert.Equal(
            MeshFormat.Glb,
            CommandLine.Parse(new[] { "dump" }, 1, DumpOptions).MeshFormat());
    }

    [Fact]
    public void MeshFormat_UnknownValue_ThrowsRatherThanSilentlyWritingMeshes()
    {
        CommandLine parsed = CommandLine.Parse(new[] { "dump", "--meshes", "gltf" }, 1, DumpOptions);

        Assert.Throws<UsageError>(() => parsed.MeshFormat());
    }

    [Theory]
    [InlineData("needed", FaceScope.Needed)]
    [InlineData("all", FaceScope.All)]
    public void FaceScope_ReadsTheOption(string value, FaceScope expected)
    {
        CommandLine parsed = CommandLine.Parse(new[] { "dump", "--faces", value }, 1, DumpOptions);

        Assert.Equal(expected, parsed.FaceScope());
    }

    [Fact]
    public void FaceScope_DefaultsToNeeded()
    {
        Assert.Equal(
            FaceScope.Needed,
            CommandLine.Parse(new[] { "dump" }, 1, DumpOptions).FaceScope());
    }

    [Fact]
    public void FaceScope_UnknownValue_Throws()
    {
        CommandLine parsed = CommandLine.Parse(new[] { "dump", "--faces", "some" }, 1, DumpOptions);

        Assert.Throws<UsageError>(() => parsed.FaceScope());
    }
}
