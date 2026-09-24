using System;
using System.Collections.Generic;
using System.Linq;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Probes;

/// <summary>Which open document a drawing probe runs on (feature 011, contracts/probes.md section 2).</summary>
public enum DrawingProbeTarget
{
    /// <summary>An open drawing: the probe reads the drawing's own extraction.</summary>
    Drawing,

    /// <summary>A part or an assembly: the probe asks about the drawing beside it.</summary>
    Model,

    /// <summary>Whatever is open: the probe lists the session's documents.</summary>
    Any,
}

/// <summary>One probe of <c>swreview-extract probe drawings</c>: its id, what it runs on, and where its answer is recorded.</summary>
public sealed class DrawingProbeDefinition
{
    internal DrawingProbeDefinition(
        string id, string title, DrawingProbeTarget target, string runOn, string recordedIn, bool opensADocument = false)
    {
        Id = id;
        Title = title;
        Target = target;
        RunOn = runOn;
        RecordedIn = recordedIn;
        OpensADocument = opensADocument;
    }

    /// <summary><c>D1</c> to <c>D14</c>.</summary>
    public string Id { get; }

    /// <summary>What the section prints, as its header says it.</summary>
    public string Title { get; }

    public DrawingProbeTarget Target { get; }

    /// <summary>The set-up the contract's table names, printed under the header so the report says what it was run on.</summary>
    public string RunOn { get; }

    /// <summary>Where the owner records the answer (research R4 and the task that reads it).</summary>
    public string RecordedIn { get; }

    /// <summary>
    /// True for D14 alone: the one probe that opens a document (the confirmed candidate's
    /// read-only open, contracts/confirmed-open.md). It runs only when named.
    /// </summary>
    public bool OpensADocument { get; }

    /// <summary>Whether this probe reads anything on a document of <paramref name="kind"/>.</summary>
    public bool AppliesTo(DocumentKind kind) =>
        Target == DrawingProbeTarget.Any
        || (Target == DrawingProbeTarget.Drawing) == (kind == DocumentKind.Drawing);
}

/// <summary>
/// Feature 011 T081 (contracts/probes.md section 2): the fourteen probes of
/// <c>swreview-extract probe drawings</c>, in the contract's order. One list, so the command's
/// validation, its default selection, the report and the tests cannot disagree about which probes
/// exist or what each runs on.
/// </summary>
public static class DrawingProbeCatalog
{
    private static readonly DrawingProbeDefinition[] Definitions =
    {
        new DrawingProbeDefinition(
            "D1", "the Standards extraction", DrawingProbeTarget.Drawing,
            "an open multi-sheet drawing", "R4, 006 T107"),
        new DrawingProbeDefinition(
            "D2", "the open documents", DrawingProbeTarget.Any,
            "a model with three drawings open, one hidden behind another window", "R4"),
        new DrawingProbeDefinition(
            "D3", "the views of every sheet, from the document and from each sheet", DrawingProbeTarget.Drawing,
            "a six-sheet drawing, sheet 3 active", "R4, 006 T103"),
        new DrawingProbeDefinition(
            "D4", "dimension precision and units", DrawingProbeTarget.Drawing,
            "a drawing with dimensions at their own precision and at the document's", "R4, drawing-source.md section 2"),
        new DrawingProbeDefinition(
            "D5", "dimension tolerances, against the part's own reading", DrawingProbeTarget.Drawing,
            "a drawing with a model-item and a reference dimension on one hole", "R4"),
        new DrawingProbeDefinition(
            "D6", "annotation attachments, against the part's face phase", DrawingProbeTarget.Drawing,
            "a part drawing and an assembly drawing of one part, with a diameter, a hole callout and a GTol on known holes",
            "R4, T066"),
        new DrawingProbeDefinition(
            "D7", "hole callouts", DrawingProbeTarget.Drawing,
            "a counterbore callout", "R4"),
        new DrawingProbeDefinition(
            "D8", "dimension full names, against the part's", DrawingProbeTarget.Drawing,
            "the D5 drawing", "R4, T066"),
        new DrawingProbeDefinition(
            "D9", "geometric tolerances, datums and surface finish", DrawingProbeTarget.Drawing,
            "a drawing with GTols, datums and surface-finish symbols", "R4"),
        new DrawingProbeDefinition(
            "D10", "tables", DrawingProbeTarget.Drawing,
            "a drawing with one table of each kind", "R4"),
        new DrawingProbeDefinition(
            "D11", "sheet properties and document settings", DrawingProbeTarget.Drawing,
            "the D1 drawing", "R4"),
        new DrawingProbeDefinition(
            "D12", "view state and detailing mode", DrawingProbeTarget.Drawing,
            "an up-to-date view, a view left out of date after a model edit, and a drawing in detailing mode", "R4"),
        new DrawingProbeDefinition(
            "D13", "the candidate check", DrawingProbeTarget.Model,
            "a reviewed part in a vault view whose same-name drawing is not cached locally", "R4"),
        new DrawingProbeDefinition(
            "D14", "the read-only open of a confirmed candidate", DrawingProbeTarget.Model,
            "a reviewed part whose same-name drawing is not open, then the same with the drawing open",
            "R4, T077, SC-011", opensADocument: true),
    };

    /// <summary>Every probe, D1 to D14.</summary>
    public static IReadOnlyList<DrawingProbeDefinition> All { get; } = Definitions;

    /// <summary>Every probe id, in order.</summary>
    public static IReadOnlyList<string> AllIds { get; } = Definitions.Select(probe => probe.Id).ToArray();

    /// <summary>Whether <paramref name="id"/> is a probe id exactly as the catalog spells it.</summary>
    public static bool IsKnown(string? id) =>
        id != null && Definitions.Any(probe => string.Equals(probe.Id, id, StringComparison.Ordinal));

    public static DrawingProbeDefinition Get(string id) =>
        Definitions.FirstOrDefault(probe => string.Equals(probe.Id, id, StringComparison.Ordinal))
        ?? throw new ArgumentException($"'{id}' is not a drawing probe; the probes are {string.Join(", ", AllIds)}.", nameof(id));

    /// <summary>
    /// The probes run when <c>--probe</c> is not given: every one that applies to the open
    /// document's kind, except D14 - the one probe that opens a document runs only when named.
    /// </summary>
    public static IReadOnlyList<string> DefaultFor(DocumentKind kind) =>
        Definitions.Where(probe => probe.AppliesTo(kind) && !probe.OpensADocument).Select(probe => probe.Id).ToArray();

    /// <summary><paramref name="ids"/> once each, in the catalog's order; an unknown id is dropped.</summary>
    public static IReadOnlyList<string> InCatalogOrder(IEnumerable<string> ids)
    {
        var wanted = new HashSet<string>(ids ?? Array.Empty<string>(), StringComparer.Ordinal);
        return AllIds.Where(wanted.Contains).ToArray();
    }
}

/// <summary>What <c>probe drawings</c> was asked to do (contracts/probes.md section 1).</summary>
public sealed class DrawingProbeSettings
{
    /// <summary><c>--out</c>: the folder the report is written in. Nothing else is written anywhere.</summary>
    public string OutputDirectory { get; set; } = string.Empty;

    /// <summary><c>--doc</c>: an open drawing or model; null means the active document.</summary>
    public string? DocumentPath { get; set; }

    /// <summary><c>--probe</c>, in catalog order; null means the default for the open document's kind.</summary>
    public IReadOnlyList<string>? ProbeIds { get; set; }
}
