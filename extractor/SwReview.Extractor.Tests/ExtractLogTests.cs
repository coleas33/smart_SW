using System;
using System.IO;
using SwReview.Extractor.Console;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// 004 T330 (owner decision 166A; research R27.1): the console's log is on disk line by line, so
/// a run that hangs, is stopped with Ctrl+C or crashes keeps every line it wrote before that.
/// The file is read while the log still holds it, as a hung run's would be.
/// </summary>
public sealed class ExtractLogTests : IDisposable
{
    private readonly string _directory =
        Path.Combine(Path.GetTempPath(), "swreview-tests", Guid.NewGuid().ToString("N"));

    public void Dispose()
    {
        if (Directory.Exists(_directory))
        {
            Directory.Delete(_directory, recursive: true);
        }
    }

    private string ReadWhileOpen(string fileName)
    {
        using (var stream = new FileStream(
            Path.Combine(_directory, fileName), FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
        using (var reader = new StreamReader(stream))
        {
            return reader.ReadToEnd();
        }
    }

    [Fact]
    public void EachLineIsInTheFileBeforeTheLogIsDisposed()
    {
        using (var log = new ExtractLog(_directory, "probe.log"))
        {
            log.Write("first line");
            Assert.Contains("first line", ReadWhileOpen("probe.log"), StringComparison.Ordinal);

            log.Write("second line");
            string text = ReadWhileOpen("probe.log");
            Assert.Contains("first line", text, StringComparison.Ordinal);
            Assert.Contains("second line", text, StringComparison.Ordinal);
        }
    }

    [Fact]
    public void AnErrorsLinesAreInTheFileBeforeTheLogIsDisposed()
    {
        using (var log = new ExtractLog(_directory, "probe.log"))
        {
            log.WriteError("probe remodel failed.", new InvalidOperationException("the fake's words"));

            string text = ReadWhileOpen("probe.log");
            Assert.Contains("probe remodel failed.", text, StringComparison.Ordinal);
            Assert.Contains(nameof(InvalidOperationException), text, StringComparison.Ordinal);
        }
    }

    [Fact]
    public void ALaterRunAppendsToTheSameFile()
    {
        using (var log = new ExtractLog(_directory, "probe.log"))
        {
            log.Write("run one");
        }

        using (var log = new ExtractLog(_directory, "probe.log"))
        {
            log.Write("run two");
        }

        string text = File.ReadAllText(Path.Combine(_directory, "probe.log"));
        Assert.True(text.IndexOf("run one", StringComparison.Ordinal) < text.IndexOf("run two", StringComparison.Ordinal));
    }

    [Fact]
    public void ALogWhoseFileCannotBeOpenedNeverThrows()
    {
        // A folder where the file should be: the open fails, and the run goes on to the console only.
        Directory.CreateDirectory(Path.Combine(_directory, "taken.log"));

        using (var log = new ExtractLog(_directory, "taken.log"))
        {
            log.Write("still runs");
            log.WriteError("still runs", new InvalidOperationException("x"));
        }
    }
}
