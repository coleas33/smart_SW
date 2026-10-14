using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Dump;

/// <summary>
/// Flushed crash diagnostics beside package.json. Only symbolic stages and guarded member
/// names are recorded, never model paths, values or exception messages. A gate marker is an
/// attempted guard check, not proof that the native call ran or returned.
/// </summary>
public sealed class ExtractionProgress : IDisposable
{
    public const string FileName = "extraction-progress.jsonl";
    private readonly StreamWriter _writer;
    private string _phase = "attach";
    private long _sequence;
    private bool _unavailable;

    public ExtractionProgress(string outputDirectory)
    {
        if (string.IsNullOrWhiteSpace(outputDirectory))
            throw new ArgumentException("An output directory is required.", nameof(outputDirectory));
        Directory.CreateDirectory(outputDirectory);
        _writer = new StreamWriter(new FileStream(
            Path.Combine(outputDirectory, FileName), FileMode.Create, FileAccess.Write,
            FileShare.ReadWrite), new UTF8Encoding(false)) { AutoFlush = true };
    }

    public void Phase(string phase, string state)
    {
        _phase = Symbol(phase);
        Record(state);
    }

    public T Step<T>(string phase, Func<T> work)
    {
        Phase(phase, "before");
        try
        {
            T result = work();
            Phase(phase, "after");
            return result;
        }
        catch (Exception failure)
        {
            Failed(failure);
            throw;
        }
    }

    public void Failed(Exception failure) => Record("failed", exception: failure.GetType().Name);

    /// <summary>Temporarily observes this gate, preserving an existing observer and its refusals.</summary>
    public IDisposable? Observe(SwGate? gate) => gate == null
        || gate.Observer is Observation current && current.IsFor(this) ? null : new Observation(this, gate);

    private void Record(string state, string? member = null, string? exception = null)
    {
        if (_unavailable) return;
        var row = new Dictionary<string, object?>
        {
            { "sequence", ++_sequence }, { "phase", _phase }, { "state", Symbol(state) },
        };
        if (member != null) row["member"] = Symbol(member);
        if (exception != null) row["exception_type"] = Symbol(exception);
        try { _writer.WriteLine(JsonSerializer.Serialize(row)); }
        catch (IOException) { _unavailable = true; }
        catch (UnauthorizedAccessException) { _unavailable = true; }
        catch (ObjectDisposedException) { _unavailable = true; }
    }

    private static string Symbol(string value) => value.Length > 0 && value.Length <= 160
        && value.All(c => c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z'
            || c >= '0' && c <= '9' || c == '_' || c == '.' || c == '-') ? value : "unknown";

    public void Dispose()
    {
        _unavailable = true;
        try { _writer.Dispose(); }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }

    private sealed class Observation : ISwGateObserver, IDisposable
    {
        private readonly ExtractionProgress _progress;
        private readonly SwGate _gate;
        private readonly ISwGateObserver? _previous;

        public Observation(ExtractionProgress progress, SwGate gate)
        {
            _progress = progress;
            _gate = gate;
            _previous = gate.Observer;
            gate.Observer = this;
        }

        public bool IsFor(ExtractionProgress progress) => ReferenceEquals(_progress, progress);

        public void Gated(string member)
        {
            _progress.Record("gated", member);
            _previous?.Gated(member);
        }

        public void Refused(MutatingCallError refusal)
        {
            _progress.Record("refused", refusal.MemberName);
            _previous?.Refused(refusal);
        }

        public void Dispose()
        {
            if (ReferenceEquals(_gate.Observer, this)) _gate.Observer = _previous;
        }
    }
}
