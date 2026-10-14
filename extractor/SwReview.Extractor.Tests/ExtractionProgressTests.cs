using System;
using System.Collections.Generic;
using System.IO;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.Extractor.Tests;

public sealed class ExtractionProgressTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "swreview-tests", Guid.NewGuid().ToString("N"));

    [Fact]
    public void GateObservationPreservesExistingAuditAndMutationRefusal()
    {
        var original = new Audit();
        var gate = new SwGate { Observer = original };
        bool mutated = false;
        using (var progress = new ExtractionProgress(_root))
        using (progress.Observe(gate))
        {
            progress.Phase("drawing", "before");
            Assert.Equal("FICT-private-design-path", gate.Call("GetPathName", () => "FICT-private-design-path"));
            Assert.Throws<MutatingCallError>(() => gate.Call("ForceRebuild3", () => mutated = true));
        }
        Assert.False(mutated);
        Assert.Same(original, gate.Observer);
        Assert.Equal(new[] { "GetPathName", "ForceRebuild3" }, original.Members);
        Assert.Equal(1, original.Refusals);
        string trace = File.ReadAllText(Path.Combine(_root, ExtractionProgress.FileName));
        Assert.Contains("\"state\":\"gated\",\"member\":\"GetPathName\"", trace, StringComparison.Ordinal);
        Assert.Contains("\"state\":\"refused\",\"member\":\"ForceRebuild3\"", trace, StringComparison.Ordinal);
        Assert.DoesNotContain("FICT-private-design-path", trace, StringComparison.Ordinal);
    }

    [Fact]
    public void NestedObservationOnSameGateDoesNotDuplicateMarkersOrAudit()
    {
        var original = new Audit();
        var gate = new SwGate { Observer = original };
        using (var progress = new ExtractionProgress(_root))
        using (progress.Observe(gate))
        using (progress.Observe(gate))
            gate.Call("GetPathName", () => 7);
        Assert.Same(original, gate.Observer);
        Assert.Single(original.Members);
        Assert.Single(File.ReadAllLines(Path.Combine(_root, ExtractionProgress.FileName)));
    }

    [Fact]
    public void ObservationRestoresExistingObserverAfterReaderThrows()
    {
        var original = new Audit();
        var gate = new SwGate { Observer = original };
        Assert.Throws<InvalidOperationException>(() =>
        {
            using var progress = new ExtractionProgress(_root);
            using IDisposable? observation = progress.Observe(gate);
            progress.Step<int>("drawing", () => gate.Call<int>("GetViews", () =>
                throw new InvalidOperationException("FICT-private-exception-message")));
        });
        Assert.Same(original, gate.Observer);
        string trace = File.ReadAllText(Path.Combine(_root, ExtractionProgress.FileName));
        Assert.Contains("InvalidOperationException", trace, StringComparison.Ordinal);
        Assert.DoesNotContain("FICT-private-exception-message", trace, StringComparison.Ordinal);
    }

    [Fact]
    public void ObservationDoesNotOverwriteAnotherObserverInstalledDuringRun()
    {
        var gate = new SwGate();
        var later = new Audit();
        using (var progress = new ExtractionProgress(_root))
        using (progress.Observe(gate)) gate.Observer = later;
        Assert.Same(later, gate.Observer);
    }

    [Fact]
    public void DiagnosticSymbolsRejectPathsAndLateObservationDoesNotBreakReads()
    {
        var gate = new SwGate();
        using var progress = new ExtractionProgress(_root);
        using IDisposable? observation = progress.Observe(gate);
        gate.Observer!.Gated(@"C:\FICT-private\fixture.SLDPRT");
        progress.Dispose();
        Assert.Equal(8, gate.Call("GetPathName", () => 8));
        string trace = File.ReadAllText(Path.Combine(_root, ExtractionProgress.FileName));
        Assert.Contains("\"member\":\"unknown\"", trace, StringComparison.Ordinal);
        Assert.DoesNotContain("FICT-private", trace, StringComparison.Ordinal);
    }

    public void Dispose()
    {
        if (Directory.Exists(_root)) Directory.Delete(_root, recursive: true);
    }

    private sealed class Audit : ISwGateObserver
    {
        public List<string> Members { get; } = new List<string>();
        public int Refusals { get; private set; }
        public void Gated(string member) => Members.Add(member);
        public void Refused(MutatingCallError refusal) => Refusals++;
    }
}
