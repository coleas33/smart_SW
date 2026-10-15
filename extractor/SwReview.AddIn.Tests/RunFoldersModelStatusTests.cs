using System;
using System.IO;
using System.Text;
using System.Text.Json;
using SwReview.AddIn.Review;
using SwReview.Extractor.Dump;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>T073: the one bounded session head read used to refresh waiting chips.</summary>
public sealed class RunFoldersModelStatusTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "SwReview.ModelStatus.Tests", Guid.NewGuid().ToString("N"));

    public RunFoldersModelStatusTests() { Directory.CreateDirectory(_root); }

    public void Dispose() { Directory.Delete(_root, recursive: true); }

    [Theory]
    [InlineData("not_sent")]
    [InlineData("send_failed")]
    [InlineData("sent")]
    public void TheReaderReturnsOnlyTheTopLevelStatusAndStopsParsingAfterIt(string state)
    {
        string json = "{\"nested\":{\"model_status\":{\"state\":\"wrong\"}},\"model_status\":{\"state\":\""
            + state + "\",\"document\":{\"path\":\"FICT-part\"}}, broken tail";
        var stream = new ChunkedHead(Encoding.UTF8.GetBytes(json), 7);
        JsonElement? status = RunFolders.ReadModelStatus(_root, path =>
        {
            Assert.Equal(Path.Combine(_root, "session.json"), path);
            return stream;
        });
        Assert.True(status.HasValue);
        Assert.Equal(state, status.Value.GetProperty("state").GetString());
        Assert.Equal("FICT-part", status.Value.GetProperty("document").GetProperty("path").GetString());
        Assert.True(stream.Disposed);
        Assert.True(stream.Reads > 1, "the head must be filled across short reads");
    }

    [Theory]
    [InlineData("{}")]
    [InlineData("{\"nested\":{\"model_status\":{\"state\":\"sent\"}}}")]
    [InlineData("{\"model_status\":null}")]
    [InlineData("{\"model_status\":false}")]
    [InlineData("{\"model_status\":{\"state\":\"sent\"")]
    [InlineData("this is not JSON")]
    public void AnAbsentOrUnreadableStatusIsNull(string json)
    {
        Assert.Null(RunFolders.ReadModelStatus(_root,
            _ => new MemoryStream(Encoding.UTF8.GetBytes(json))));
    }

    [Fact]
    public void NoFileAndAnInvalidRunPathAreNull()
    {
        Assert.Null(RunFolders.ReadModelStatus(_root));
        Assert.Null(RunFolders.ReadModelStatus(null));
        Assert.Null(RunFolders.ReadModelStatus("\0bad"));
    }

    [Fact]
    public void AnUnreadableOpenerOrStreamNeverEscapes()
    {
        Assert.Null(RunFolders.ReadModelStatus(_root, _ => throw new IOException("FICT locked")));
        Assert.Null(RunFolders.ReadModelStatus(_root, _ => throw new UnauthorizedAccessException("FICT denied")));
        Assert.Null(RunFolders.ReadModelStatus(_root, _ => new UnreadableHead()));
    }

    [Fact]
    public void TheHeadReadNeverRequestsABytePast65536()
    {
        string json = "{\"padding\":\"" + new string('x', 65536) + "\",\"model_status\":{\"state\":\"sent\"}}";
        var stream = new ChunkedHead(Encoding.UTF8.GetBytes(json), 257, cap: 65536);
        Assert.Null(RunFolders.ReadModelStatus(_root, _ => stream));
        Assert.Equal(65536, stream.BytesRead);
        Assert.False(stream.AttemptedPastCap, "even a refused over-read must be recorded");
        Assert.True(stream.Disposed);
    }

    [Fact]
    public void TheExtractedFillLoopCapsAndTrimsShortStreams()
    {
        var bounded = new ChunkedHead(Encoding.UTF8.GetBytes("FICT more than a head"), 2, cap: 4);
        Assert.Equal("FICT", Encoding.UTF8.GetString(PackageIndex.FillHead(bounded, 4)));
        Assert.Equal(4, bounded.BytesRead);
        var shortStream = new ChunkedHead(Encoding.UTF8.GetBytes("FICT"), 1);
        Assert.Equal("FICT", Encoding.UTF8.GetString(PackageIndex.FillHead(shortStream, 128)));
    }

    [Fact]
    public void TheActualDefaultOpenerAllowsReplaceWhileItsFileIsHeld()
    {
        string path = Path.Combine(_root, "session.json");
        string next = Path.Combine(_root, "next.json");
        File.WriteAllText(path, "{\"model_status\":{\"state\":\"not_sent\"}}");
        File.WriteAllText(next, "{\"model_status\":{\"state\":\"sent\"}}");
        using (Stream held = RunFolders.OpenSessionHead(path))
        {
            Assert.IsType<FileStream>(held);
            File.Replace(next, path, null);
        }
        Assert.Equal("sent", RunFolders.ReadModelStatus(_root)!.Value.GetProperty("state").GetString());
    }

    private sealed class UnreadableHead : MemoryStream
    {
        public override int Read(byte[] buffer, int offset, int count) => throw new IOException("FICT interrupted read");
    }

    private sealed class ChunkedHead : MemoryStream
    {
        private readonly int _chunk;
        private readonly int _cap;
        public ChunkedHead(byte[] bytes, int chunk, int cap = int.MaxValue) : base(bytes) { _chunk = chunk; _cap = cap; }
        public int BytesRead { get; private set; }
        public int Reads { get; private set; }
        public bool Disposed { get; private set; }
        public bool AttemptedPastCap { get; private set; }
        public override int Read(byte[] buffer, int offset, int count)
        {
            if (count > _cap - BytesRead) AttemptedPastCap = true;
            Assert.True(count <= _cap - BytesRead, "the reader requested bytes past the cap");
            int read = base.Read(buffer, offset, Math.Min(_chunk, count));
            BytesRead += read;
            Reads++;
            return read;
        }
        protected override void Dispose(bool disposing) { Disposed = true; base.Dispose(disposing); }
    }
}
