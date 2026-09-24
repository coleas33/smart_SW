using System;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Probes;

/// <summary>
/// Everything <see cref="DrawingProbeRunner"/> reads through, so every probe's rules are tested with
/// fakes and the console only wires SOLIDWORKS in (feature 011 T081). Every member is required: a
/// probe with nothing to read through would print nothing, and that silence is what the report
/// exists to break.
/// </summary>
public sealed class DrawingProbeContext
{
    /// <param name="kind">The open document's kind, which decides what each probe applies to.</param>
    /// <param name="documentPath">Its path, or null or blank for a document never saved; used, never printed.</param>
    /// <param name="document">Its live handle (<c>IModelDoc2</c>), for the reads beyond the extraction.</param>
    /// <param name="build">
    /// The extraction of the open document with the options given, built and never written
    /// (<see cref="PackageWriter.Build"/>): the drawing sections read its package.
    /// </param>
    /// <param name="buildOpenModel">
    /// A Full extraction of the model at a path when SOLIDWORKS has it open, or null when it has not:
    /// D5, D6 and D8 compare the drawing with the part's own reading, and <b>nothing is opened</b> to
    /// take it.
    /// </param>
    /// <param name="openDocuments">Discovery's seam over the documents SOLIDWORKS has open (D2).</param>
    /// <param name="reads">The reads the extraction does not record (D2, D3, D7, D10, D11).</param>
    /// <param name="files">The file-system reads of D13 and D14.</param>
    /// <param name="openSeam">What D14 runs the confirmed open through.</param>
    /// <param name="clockMilliseconds">A millisecond clock for the elapsed times D1 and D13 print.</param>
    public DrawingProbeContext(
        DocumentKind kind,
        string? documentPath,
        object document,
        Func<DumpOptions, EvidencePackage> build,
        Func<string, DumpOptions, EvidencePackage?> buildOpenModel,
        IOpenDrawingSource openDocuments,
        IDrawingProbeReads reads,
        IProbeFiles files,
        DrawingOpenProbeSeam openSeam,
        Func<long> clockMilliseconds)
    {
        Kind = kind;
        DocumentPath = string.IsNullOrWhiteSpace(documentPath) ? null : documentPath!.Trim();
        Document = document ?? throw new ArgumentNullException(nameof(document));
        Build = build ?? throw new ArgumentNullException(nameof(build));
        BuildOpenModel = buildOpenModel ?? throw new ArgumentNullException(nameof(buildOpenModel));
        OpenDocuments = openDocuments ?? throw new ArgumentNullException(nameof(openDocuments));
        Reads = reads ?? throw new ArgumentNullException(nameof(reads));
        Files = files ?? throw new ArgumentNullException(nameof(files));
        OpenSeam = openSeam ?? throw new ArgumentNullException(nameof(openSeam));
        ClockMilliseconds = clockMilliseconds ?? throw new ArgumentNullException(nameof(clockMilliseconds));
    }

    public DocumentKind Kind { get; }

    /// <summary>The document's path, trimmed; null when it was never saved.</summary>
    public string? DocumentPath { get; }

    public object Document { get; }

    public Func<DumpOptions, EvidencePackage> Build { get; }

    public Func<string, DumpOptions, EvidencePackage?> BuildOpenModel { get; }

    public IOpenDrawingSource OpenDocuments { get; }

    public IDrawingProbeReads Reads { get; }

    public IProbeFiles Files { get; }

    public DrawingOpenProbeSeam OpenSeam { get; }

    public Func<long> ClockMilliseconds { get; }
}
