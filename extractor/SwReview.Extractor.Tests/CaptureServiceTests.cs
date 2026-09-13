using System;
using System.IO;
using System.Linq;
using SwReview.Extractor.Capture;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Tests.Fakes;
using Xunit;
using IrCapture = SwReview.Extractor.Ir.Capture;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T070. File naming, the <c>--view</c> mapping, and what a failed capture becomes.
///
/// The naming matters more than it looks: <c>Capture.file</c> is what the report links to,
/// the schema insists it ends in <c>.png</c>, and a capture id contains a colon that Windows
/// will not put in a file name.
/// </summary>
public class CaptureServiceTests : IDisposable
{
    private readonly string _outputDirectory;

    public CaptureServiceTests()
    {
        _outputDirectory = Path.Combine(
            Path.GetTempPath(), "swreview-tests", Guid.NewGuid().ToString("N"));
    }

    public void Dispose()
    {
        if (Directory.Exists(_outputDirectory))
        {
            Directory.Delete(_outputDirectory, recursive: true);
        }
    }

    // ---- naming ------------------------------------------------------------------

    [Fact]
    public void RelativeFile_IsPackageRelativeAndForwardSlashed()
    {
        // The Python reviewer joins this to the package directory on whatever platform it
        // runs on, so the separator is not the C# one.
        Assert.Equal("captures/cap-0001.png", CaptureService.RelativeFile("cap:0001"));
    }

    [Fact]
    public void FileName_ReplacesTheColonWindowsCannotStore()
    {
        Assert.Equal("cap-0042.png", CaptureService.FileName("cap:0042"));
    }

    [Fact]
    public void Capture_FileNameFollowsTheCaptureId()
    {
        var view = new FakeCaptureView();
        CaptureResult result = new CaptureService(view).Capture(
            "cmVm", null, CaptureViews.Iso, _outputDirectory);

        Assert.Equal("cap:0001", result.Capture!.Id);
        Assert.Equal("captures/cap-0001.png", result.Capture.File);
    }

    [Fact]
    public void Capture_WritesUnderTheCapturesSubdirectory()
    {
        var view = new FakeCaptureView();
        new CaptureService(view).Capture("cmVm", null, CaptureViews.Iso, _outputDirectory);

        string expected = Path.Combine(_outputDirectory, "captures", "cap-0001.png");
        Assert.Equal(expected, Assert.Single(view.SavedPaths));
        Assert.True(File.Exists(expected));
    }

    [Fact]
    public void Capture_IdsCountUpWithinOneService()
    {
        var service = new CaptureService(new FakeCaptureView());

        CaptureResult first = service.Capture("a", null, CaptureViews.Fit, _outputDirectory);
        CaptureResult second = service.Capture("b", null, CaptureViews.Fit, _outputDirectory);

        Assert.Equal("cap:0001", first.Capture!.Id);
        Assert.Equal("cap:0002", second.Capture!.Id);
        Assert.NotEqual(first.Capture.File, second.Capture.File);
    }

    [Fact]
    public void Capture_ContinuesFromAnAllocatorThePackageSeeded()
    {
        // T071: appending to a package that already holds cap:0003 must not overwrite it.
        var service = new CaptureService(new FakeCaptureView(), new IdAllocator("cap", 3));

        CaptureResult result = service.Capture("a", null, CaptureViews.Fit, _outputDirectory);

        Assert.Equal("cap:0004", result.Capture!.Id);
    }

    [Fact]
    public void Capture_FileAlwaysEndsInPngAsTheSchemaRequires()
    {
        CaptureResult result = new CaptureService(new FakeCaptureView()).Capture(
            "cmVm", null, CaptureViews.Top, _outputDirectory);

        Assert.EndsWith(".png", result.Capture!.File, StringComparison.Ordinal);
    }

    // ---- the view mapping --------------------------------------------------------

    [Theory]
    [InlineData("iso", "*Isometric")]
    [InlineData("front", "*Front")]
    [InlineData("top", "*Top")]
    [InlineData("right", "*Right")]
    public void NamedView_MapsEachContractValueToItsStandardView(string view, string expected)
    {
        Assert.Equal(expected, CaptureViews.NamedView(view));
    }

    [Fact]
    public void NamedView_FitIsNotANamedView()
    {
        Assert.Null(CaptureViews.NamedView(CaptureViews.Fit));
    }

    [Fact]
    public void NamedView_UnknownValue_Throws()
    {
        // A view name the agent invented must never reach interop.
        Assert.Throws<ArgumentException>(() => CaptureViews.NamedView("behind"));
    }

    [Fact]
    public void Capture_NamedView_ShowsItThroughTheView()
    {
        var view = new FakeCaptureView();
        new CaptureService(view).Capture("cmVm", null, "front", _outputDirectory);

        Assert.Equal("*Front", Assert.Single(view.NamedViews));
    }

    [Fact]
    public void Capture_FitView_RotatesNothing()
    {
        var view = new FakeCaptureView();
        new CaptureService(view).Capture("cmVm", null, CaptureViews.Fit, _outputDirectory);

        Assert.Empty(view.NamedViews);
        Assert.Equal(new[] { "select", "zoom", "save" }, view.Calls);
    }

    [Fact]
    public void Capture_ZoomsAgainAfterRotating()
    {
        // ShowNamedView2 keeps the zoom but moves the camera, so the second zoom is what
        // keeps the selection framed.
        var view = new FakeCaptureView();
        new CaptureService(view).Capture("cmVm", null, CaptureViews.Iso, _outputDirectory);

        Assert.Equal(new[] { "select", "zoom", "view:*Isometric", "zoom", "save" }, view.Calls);
    }

    [Fact]
    public void Capture_RecordsTheNormalizedViewName()
    {
        CaptureResult result = new CaptureService(new FakeCaptureView()).Capture(
            "cmVm", null, "ISO", _outputDirectory);

        Assert.Equal("iso", result.Capture!.View);
    }

    [Fact]
    public void Capture_UnknownView_IsAGapNotAnException()
    {
        CaptureResult result = new CaptureService(new FakeCaptureView()).Capture(
            "cmVm", null, "behind", _outputDirectory);

        Assert.False(result.Succeeded);
        Assert.Equal(GapKind.Unsupported, result.Gap!.Kind);
        Assert.Equal(CaptureService.GapEntityKind, result.Gap.EntityKind);
    }

    // ---- what the row carries ----------------------------------------------------

    [Fact]
    public void Capture_RecordsThePersistRefAndComponentIds()
    {
        var view = new FakeCaptureView();
        CaptureResult result = new CaptureService(view).Capture(
            "cmVm", @"C:\work\bracket.SLDPRT", CaptureViews.Iso, _outputDirectory, "why it matters");

        IrCapture capture = result.Capture!;
        Assert.Equal("cmVm", capture.PersistRef);
        Assert.Equal(new[] { "cmp:0007" }, capture.ComponentIds);
        Assert.Equal("why it matters", capture.Note);
        Assert.Equal(@"C:\work\bracket.SLDPRT", view.SelectedScope);
    }

    // ---- failure -----------------------------------------------------------------

    [Fact]
    public void Capture_ReferenceThatDoesNotResolve_IsAGapWithTheReason()
    {
        var view = new FakeCaptureView { SelectFailure = "deleted: the entity no longer exists" };

        CaptureResult result = new CaptureService(view).Capture(
            "cmVm", null, CaptureViews.Iso, _outputDirectory);

        Assert.False(result.Succeeded);
        Assert.Null(result.Capture);
        Assert.Equal(GapKind.NotExtracted, result.Gap!.Kind);
        Assert.Contains("deleted", result.Gap.Error!, StringComparison.Ordinal);
        Assert.Empty(view.SavedPaths);
    }

    [Fact]
    public void Capture_RefusedWrite_IsAToolErrorGap()
    {
        var view = new FakeCaptureView { SaveFails = true };

        CaptureResult result = new CaptureService(view).Capture(
            "cmVm", null, CaptureViews.Iso, _outputDirectory);

        Assert.False(result.Succeeded);
        Assert.Equal(GapKind.ToolError, result.Gap!.Kind);
    }

    [Fact]
    public void Capture_CallThatThrows_IsAGapNotAnException()
    {
        var view = new FakeCaptureView
        {
            ThrowOnZoom = new InvalidOperationException("the view is gone"),
        };

        CaptureResult result = new CaptureService(view).Capture(
            "cmVm", null, CaptureViews.Iso, _outputDirectory);

        Assert.False(result.Succeeded);
        Assert.Contains("the view is gone", result.Gap!.Error!, StringComparison.Ordinal);
    }

    [Fact]
    public void Capture_CircuitOpen_PropagatesSoTheCallerStops()
    {
        var view = new FakeCaptureView
        {
            ThrowOnZoom = new CircuitOpenError("SOLIDWORKS stopped answering"),
        };

        Assert.Throws<CircuitOpenError>(() =>
            new CaptureService(view).Capture("cmVm", null, CaptureViews.Iso, _outputDirectory));
    }

    [Fact]
    public void Capture_MutatingCall_PropagatesBecauseItIsOurBug()
    {
        var view = new FakeCaptureView
        {
            ThrowOnZoom = new MutatingCallError("Save3", "Save3 modifies the model."),
        };

        Assert.Throws<MutatingCallError>(() =>
            new CaptureService(view).Capture("cmVm", null, CaptureViews.Iso, _outputDirectory));
    }

    [Fact]
    public void Capture_BlankArguments_Throw()
    {
        var service = new CaptureService(new FakeCaptureView());

        Assert.Throws<ArgumentException>(() =>
            service.Capture(" ", null, CaptureViews.Iso, _outputDirectory));
        Assert.Throws<ArgumentException>(() => service.Capture("cmVm", null, CaptureViews.Iso, " "));
        Assert.Throws<ArgumentNullException>(() => new CaptureService(null!));
    }
}
