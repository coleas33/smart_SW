using SwReview.AddIn.Review;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// One rule for "the same document" (feature 015 T104-T106): the path compared ignoring case,
/// as Windows names one file however it is spelled, and the configuration exactly, as
/// SOLIDWORKS names configurations.
/// </summary>
public sealed class PageDocumentTests
{
    private static readonly PageDocument Reviewed = new PageDocument(@"C:\Fictional\FICT-Assembly.SLDASM", "Default");

    [Theory]
    [InlineData(@"C:\Fictional\FICT-Assembly.SLDASM", "Default", true)]
    [InlineData(@"c:\fictional\fict-assembly.sldasm", "Default", true)]
    [InlineData(@"C:\Fictional\FICT-Assembly.SLDASM", "default", false)]
    [InlineData(@"C:\Fictional\FICT-Assembly.SLDASM", "FICT-Other", false)]
    [InlineData(@"C:\Fictional\FICT-Assembly.SLDASM", null, false)]
    [InlineData(@"C:\Fictional\FICT-Other.SLDASM", "Default", false)]
    [InlineData(null, "Default", false)]
    public void ThePathIgnoresCaseAndTheConfigurationIsExact(string? path, string? configuration, bool same)
    {
        Assert.Equal(same, Reviewed.IsSameDocument(path, configuration));
        if (path != null)
        {
            Assert.Equal(same, Reviewed.IsSameDocument(new PageDocument(path, configuration)));
        }
    }

    [Fact]
    public void NoConfigurationMatchesOnlyNoConfiguration()
    {
        var bare = new PageDocument(@"C:\Fictional\FICT-Part.SLDPRT", null);

        Assert.True(bare.IsSameDocument(@"C:\FICTIONAL\FICT-PART.SLDPRT", null));
        Assert.False(bare.IsSameDocument(@"C:\Fictional\FICT-Part.SLDPRT", "Default"));
        Assert.False(bare.IsSameDocument(null));
    }
}
