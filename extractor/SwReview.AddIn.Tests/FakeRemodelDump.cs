using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using SwReview.AddIn.Review;
using SwReview.Extractor.Dump;

namespace SwReview.AddIn.Tests;

/// <summary>
/// The extractor, as far as the Remodel pipeline is concerned: it writes a `package.json` whose
/// head says which profile wrote it, which is the thing the pipeline checks before it renames the
/// file. Shared by <see cref="BackendRemodelPipelineTests"/> and
/// <see cref="RemodelPlanEndToEndTests"/>.
/// </summary>
internal sealed class FakeRemodelDump : IReviewDump
{
    private readonly List<string> _log;

    public FakeRemodelDump(List<string> log) => _log = log;

    public List<string> Folders { get; } = new List<string>();

    public List<DumpProfile> Profiles { get; } = new List<DumpProfile>();

    /// <summary>What the written package says about itself; `full` is the wrong one.</summary>
    public string Profile { get; set; } = "model_check";

    /// <summary>
    /// Which document the written package says it read. Null is the ordinary case - the one
    /// copy in the run folder - and any other value is a dump of a document this run did not
    /// make, the source included: the extractor attaches to whatever SOLIDWORKS has active,
    /// and what it had active is only knowable from the file it wrote.
    /// </summary>
    public string? DocumentPath { get; set; }

    /// <summary>Whether the written package names a document at all.</summary>
    public bool WritesADocument { get; set; } = true;

    public DumpSummary Run(
        string outputDirectory, Action<string> progress, DumpProfile profile = DumpProfile.Full)
    {
        Folders.Add(outputDirectory);
        Profiles.Add(profile);
        _log.Add("dump");
        progress("Extracting bracket.SLDPRT [Default]...");

        Directory.CreateDirectory(outputDirectory);
        string path = Path.Combine(outputDirectory, "package.json");
        string read = DocumentPath
            ?? Path.Combine(outputDirectory, "copy", "bracket-RMS.SLDPRT");
        string documents = WritesADocument
            ? @"[{""document_id"":""doc-1"",""kind"":""part"",""path"":"
                + JsonSerializer.Serialize(read) + "}]"
            : "[]";

        File.WriteAllText(
            path,
            @"{""schema_version"":""1.4.0"",""extractor"":{""name"":""SwReview"","
            + @"""version"":""0.1.0"",""profile"":""" + Profile + @"""},""documents"":"
            + documents + "}");

        return new DumpSummary(path, components: 1, gaps: 0, documents: 1, features: 40);
    }
}
