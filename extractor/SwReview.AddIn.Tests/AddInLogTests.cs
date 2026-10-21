using System;
using System.IO;
using System.Linq;
using System.Threading;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Owner decision 159A, on review (004 T217; research R19.9; the race review's finding R2): <c>addin.log</c> keeps every
/// line. 159A sends whoever needs a failure's own sentence there - "Press View log to see why" - and the add-in appends to it
/// from several threads at once: the run's and the page's, SOLIDWORKS' and the tool-service gate's. Each append opened the
/// file sharing it for reading only, under no lock, and swallowed its failure, so an append that met another in progress
/// was lost: 501 of 4,000 lines in the review's run.
///
/// Each case writes a file of its own, in a folder of its own, through <see cref="AddInLog.Append"/>, the append
/// <see cref="AddInLog.Write"/> makes on the engineer's log: no case moves <see cref="AddInLog.Folder"/>, which is the whole
/// process's and which other classes move while these run.
/// </summary>
public sealed class AddInLogTests : IDisposable
{
    private readonly string _folder = Path.Combine(
        Path.GetTempPath(), "SwReview.AddInLog.Tests", Guid.NewGuid().ToString("N"));

    public AddInLogTests()
    {
        Directory.CreateDirectory(_folder);
    }

    private string Log => Path.Combine(_folder, "addin.log");

    public void Dispose()
    {
        try
        {
            Directory.Delete(_folder, recursive: true);
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }

    /// <summary>
    /// Test first: threads that append at once lose no line, and write none twice. Each thread swallows what an append
    /// throws, as <see cref="AddInLog.Write"/> does, so a line lost is a line missing from the file.
    /// </summary>
    [Fact]
    public void LinesAppendedFromSeveralThreadsAtOnceAreAllKeptOnce()
    {
        const int Writers = 8;
        const int Lines = 200;
        using (var go = new ManualResetEventSlim())
        {
            Thread[] writers = Enumerable.Range(0, Writers)
                .Select(writer => new Thread(() =>
                {
                    go.Wait();
                    for (int line = 0; line < Lines; line++)
                    {
                        AppendAsWriteDoes($"FICT writer {writer} line {line}");
                    }
                }) { IsBackground = true })
                .ToArray();
            foreach (Thread writer in writers)
            {
                writer.Start();
            }

            go.Set();
            Assert.All(writers, writer => Assert.True(writer.Join(TimeSpan.FromSeconds(60)), "a writer never finished"));
        }

        string[] written = File.ReadAllLines(Log);
        Assert.Equal(Writers * Lines, written.Length);
        Assert.Equal(Writers * Lines, written.Distinct(StringComparer.Ordinal).Count());
    }

    /// <summary>
    /// Test first (the race review's finding R2): a line appended while something else holds the file as an append holds it
    /// - writing, and sharing it for reading only: another process, or an add-in that appends as this one did - is written
    /// once the file is free, with the next line and before it. It was lost.
    /// </summary>
    [Fact]
    public void ALineAppendedWhileAnotherHoldsTheFileIsWrittenWithTheNextOne()
    {
        File.WriteAllText(Log, string.Empty);
        using (new FileStream(Log, FileMode.Append, FileAccess.Write, FileShare.Read))
        {
            AppendAsWriteDoes("FICT the sentence the tab sent the engineer to read");
        }

        AppendAsWriteDoes("FICT a later line");

        string[] written = File.ReadAllLines(Log);
        Assert.Equal(2, written.Length);
        Assert.EndsWith("FICT the sentence the tab sent the engineer to read", written[0], StringComparison.Ordinal);
        Assert.EndsWith("FICT a later line", written[1], StringComparison.Ordinal);
    }

    /// <summary>
    /// Test first: a line is written at once beside another writer that shares the file - another SOLIDWORKS session's
    /// add-in appending as this one does now. The append shared the file for reading only, so it was refused while the
    /// other held it.
    /// </summary>
    [Fact]
    public void ALineIsWrittenAtOnceBesideAnotherWriterThatSharesTheFile()
    {
        string written;
        using (new FileStream(Log, FileMode.Append, FileAccess.Write, FileShare.ReadWrite))
        {
            AddInLog.Append(Log, "FICT written beside another writer");
            using (var reader = new StreamReader(new FileStream(Log, FileMode.Open, FileAccess.Read, FileShare.ReadWrite)))
            {
                written = reader.ReadToEnd();
            }
        }

        Assert.Contains("FICT written beside another writer", written, StringComparison.Ordinal);
    }

    /// <summary>
    /// Test first: a file something else holds for a moment - an antivirus scan, an append of another process's - is waited
    /// out briefly, so the line is in the file when the append returns, where the engineer who reads the tab's words opens
    /// it at once. It was refused.
    /// </summary>
    [Fact]
    public void ALineWaitsOutABriefHolderAndIsInTheFileWhenTheAppendReturns()
    {
        File.WriteAllText(Log, string.Empty);
        using (var holding = new ManualResetEventSlim())
        {
            var holder = new Thread(() =>
            {
                using (new FileStream(Log, FileMode.Append, FileAccess.Write, FileShare.Read))
                {
                    holding.Set();
                    Thread.Sleep(30);
                }
            }) { IsBackground = true };
            holder.Start();
            Assert.True(holding.Wait(TimeSpan.FromSeconds(10)), "the holder never took the file");

            AddInLog.Append(Log, "FICT written once the holder let go");
            Assert.True(holder.Join(TimeSpan.FromSeconds(10)), "the holder never let go");
        }

        Assert.Contains("FICT written once the holder let go", File.ReadAllText(Log), StringComparison.Ordinal);
    }

    /// <summary>One append, whatever it throws swallowed, as <see cref="AddInLog.Write"/> swallows it.</summary>
    private void AppendAsWriteDoes(string line)
    {
        try
        {
            AddInLog.Append(Log, line);
        }
        catch (Exception)
        {
        }
    }
}
