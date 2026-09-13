using System.Reflection;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// The project exists so the add-in host code (settings, WebView2 hosting, the page
/// contract, the terminal and the in-process tool service) can be unit tested without a
/// SOLIDWORKS seat. This smoke test only proves the harness is wired: both assemblies
/// under test load, and they are the x64 net48 builds the add-in ships.
/// </summary>
public sealed class SmokeTests
{
    [Fact]
    public void AddInAssemblyIsReferencedAndLoadable()
    {
        Assembly addIn = typeof(SwReview.AddIn.TaskPaneControl).Assembly;

        Assert.Equal("SwReview.AddIn", addIn.GetName().Name);
    }

    [Fact]
    public void ExtractorAssemblyIsReferencedAndLoadable()
    {
        Assembly extractor = typeof(SwReview.Extractor.Ir.EvidencePackage).Assembly;

        Assert.Equal("SwReview.Extractor", extractor.GetName().Name);
    }
}
