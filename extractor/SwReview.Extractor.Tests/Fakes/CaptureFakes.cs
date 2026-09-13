using System;
using System.Collections.Generic;
using System.IO;
using SwReview.Extractor.Capture;
using SwReview.Extractor.Measure;

namespace SwReview.Extractor.Tests.Fakes;

/// <summary>
/// A capture view with no SOLIDWORKS: it records what it was asked to do and writes a
/// one-byte file where the real one would write a PNG, so the naming and the directory
/// layout are checked on disk.
/// </summary>
public sealed class FakeCaptureView : ICaptureView
{
    public List<string> NamedViews { get; } = new List<string>();

    public List<string> SavedPaths { get; } = new List<string>();

    /// <summary>The order of the calls, so "zoom, then rotate, then zoom" can be asserted.</summary>
    public List<string> Calls { get; } = new List<string>();

    public string? SelectedRef { get; private set; }

    public string? SelectedScope { get; private set; }

    /// <summary>Set to refuse the selection; the message becomes the gap's error.</summary>
    public string? SelectFailure { get; set; }

    /// <summary>Set to make SaveImage return false, the way a refused write does.</summary>
    public bool SaveFails { get; set; }

    /// <summary>Set to make a call throw, the way a stale pointer does.</summary>
    public Exception? ThrowOnZoom { get; set; }

    public List<string> ComponentIds { get; } = new List<string> { "cmp:0007" };

    public bool TrySelect(string persistRef, string? scopeDocumentPath, out string reason)
    {
        Calls.Add("select");
        SelectedRef = persistRef;
        SelectedScope = scopeDocumentPath;

        if (SelectFailure != null)
        {
            reason = SelectFailure;
            return false;
        }

        reason = string.Empty;
        return true;
    }

    public IReadOnlyList<string> SelectedComponentIds() => ComponentIds;

    public void ZoomToSelection()
    {
        Calls.Add("zoom");
        if (ThrowOnZoom != null)
        {
            throw ThrowOnZoom;
        }
    }

    public void ShowNamedView(string namedView)
    {
        Calls.Add("view:" + namedView);
        NamedViews.Add(namedView);
    }

    public bool SaveImage(string pngPath)
    {
        Calls.Add("save");
        SavedPaths.Add(pngPath);

        if (SaveFails)
        {
            return false;
        }

        Directory.CreateDirectory(Path.GetDirectoryName(pngPath)!);
        File.WriteAllBytes(pngPath, new byte[] { 0x89 });
        return true;
    }
}

/// <summary>A measure source with a fixed answer, or a fixed refusal.</summary>
public sealed class FakeMeasureSource : IMeasureSource
{
    private readonly MeasureReading? _reading;
    private readonly string? _refusal;

    public FakeMeasureSource(MeasureReading reading)
    {
        _reading = reading;
    }

    public FakeMeasureSource(string refusal)
    {
        _refusal = refusal;
    }

    public string? LastA { get; private set; }

    public string? LastB { get; private set; }

    public MeasureReading Measure(string persistRefA, string? scopeA, string persistRefB, string? scopeB)
    {
        LastA = persistRefA;
        LastB = persistRefB;

        if (_refusal != null)
        {
            throw new MeasureNotAvailableError(_refusal);
        }

        return _reading!;
    }
}
