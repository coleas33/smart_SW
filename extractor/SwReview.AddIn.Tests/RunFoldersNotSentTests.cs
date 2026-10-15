using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Json;
using SwReview.AddIn.Review;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>T105: names first, then one bounded head of the newest review only.</summary>
public sealed class RunFoldersNotSentTests : IDisposable
{
    private static readonly PageDocument Document = new PageDocument(@"C:\Fictional\FICT-Part.SLDPRT", "FICT-Default");
    private const string CheckedAt = "2026-10-12T23:17:42+09:30";
    private readonly string _root = Path.Combine(Path.GetTempPath(), "FICT-NotSent.Tests", Guid.NewGuid().ToString("N"));

    public RunFoldersNotSentTests() { Directory.CreateDirectory(_root); }

    public void Dispose() { Directory.Delete(_root, recursive: true); }

    [Theory]
    [InlineData("not_sent")]
    [InlineData("send_failed")]
    public void TheNewestWaitingReviewKeepsItsSessionIdStoredDocumentTimeAndState(string state)
    {
        string storedPath = Document.Path.ToLowerInvariant();
        string folder = Save("20261012-231742-FICT-Part", state, storedPath);

        SessionRecord found = Assert.IsType<SessionRecord>(Find(_root, Document));

        Assert.Equal(folder, found.RunDirectory);
        Assert.Equal("FICT-session", found.ChatId);
        Assert.Equal(storedPath, found.Document!.Path);
        Assert.Equal(Document.Configuration, found.Document.Configuration);
        Assert.Equal(state, found.ModelStatus);
        Assert.False(found.IsCheck);
        Assert.Equal(DateTimeOffset.Parse(CheckedAt, CultureInfo.InvariantCulture), found.StartedAt);
        Assert.Equal(TimeSpan.FromMinutes(570), found.StartedAt!.Value.Offset);
        Assert.Equal(new DateTime(2026, 10, 12, 23, 17, 42), found.StartedAt.Value.DateTime);
    }

    [Theory]
    [InlineData("sent")]
    [InlineData(null)]
    public void ANewerSentOrMissingSessionBlocksAnOlderWaitingReview(string? newestState)
    {
        Save("20261011-120000-FICT-Part");
        string newest = Path.Combine(_root, "20261012-120000-FICT-Part");
        if (newestState == null) Directory.CreateDirectory(newest);
        else Save(Path.GetFileName(newest), newestState);
        int opens = 0;

        Assert.Null(Find(_root, Document, path =>
        {
            opens++;
            Assert.Equal(Path.Combine(newest, "session.json"), path);
            return File.OpenRead(path);
        }));
        Assert.Equal(1, opens);
    }

    [Theory]
    [InlineData(@"C:\Fictional\Other\FICT-Part.SLDPRT", "FICT-Default")]
    [InlineData(@"C:\Fictional\FICT-Part.SLDPRT", "fict-default")]
    [InlineData(@"C:\Fictional\FICT-Part.SLDPRT", "FICT-Other")]
    public void ANewerSameNameFolderForAnotherPathOrConfigurationBlocksTheOlderReview(string path, string configuration)
    {
        Save("20261011-120000-FICT-Part");
        Save("20261012-120000-FICT-Part", path: path, configuration: configuration);

        Assert.Null(Find(_root, Document));
    }

    [Theory]
    [InlineData("20261012-120000-FICT-Other")]
    [InlineData("20261012-120000-Other-FICT-Part")]
    [InlineData("20261012-120000-FICT-Part-extra")]
    [InlineData("20261312-120000-FICT-Part")]
    [InlineData("20261012-120000FICT-Part")]
    public void AnotherOrInvalidFolderNameIsNeverOpenedEvenWhenItsRecordNamesThisDocument(string name)
    {
        Save(name);
        int opens = 0;

        Assert.Null(Find(_root, Document, _ =>
        {
            opens++;
            throw new IOException("FICT should never be opened");
        }));
        Assert.Equal(0, opens);
    }

    [Theory]
    [InlineData("-check")]
    [InlineData("-standards")]
    [InlineData("-remodel")]
    [InlineData("-check-2")]
    [InlineData("-standards-2")]
    [InlineData("-remodel-2")]
    public void NewerCheckStandardsAndRemodelFoldersAreSkippedByName(string suffix)
    {
        string review = Save("20261011-120000-FICT-Part");
        Save("20261012-120000-FICT-Part" + suffix);

        SessionRecord found = Assert.IsType<SessionRecord>(Find(_root, Document, path =>
        {
            Assert.Equal(Path.Combine(review, "session.json"), path);
            return File.OpenRead(path);
        }));
        Assert.Equal(review, found.RunDirectory);
    }

    [Fact]
    public void CollisionSuffixesUseOrdinalNamesToBreakATimestampTie()
    {
        Save("20261012-120000-FICT-Part");
        Save("20261012-120000-FICT-Part-2");
        Save("20261012-120000-FICT-Part-10");
        string newest = Save("20261012-120000-FICT-Part-9");

        Assert.Equal(newest, Find(_root, Document)!.RunDirectory);
    }

    [Fact]
    public void FolderNamesUseTheSameCleanedAndTruncatedDocumentNameAsCreation()
    {
        var document = new PageDocument(@"C:\Fictional\FICT-" + new string('p', 70) + ".SLDASM", "FICT-Default");
        string folder = Save("20261012-120000-" + RunFolders.DocumentName(document.Path), path: document.Path);

        Assert.Equal(folder, Find(_root, document)!.RunDirectory);
    }

    [Theory]
    [InlineData("{}")]
    [InlineData("{\"session_id\":\"FICT-session\",\"model_status\":null}")]
    [InlineData("{\"model_status\":{\"state\":\"not_sent\"}}")]
    [InlineData("not JSON")]
    public void AnIncompleteOrMalformedHeadOffersNothing(string json)
    {
        string folder = Save("20261012-120000-FICT-Part");
        File.WriteAllText(Path.Combine(folder, "session.json"), json);

        Assert.Null(Find(_root, Document));
    }

    [Fact]
    public void SessionIdIsTopLevelAndTheReaderStopsAfterTheCompleteModelStatus()
    {
        string folder = Save("20261012-120000-FICT-Part");
        string json = Session("not_sent", Document.Path, Document.Configuration!);
        json = "{\"nested\":{\"session_id\":\"FICT-wrong\",\"model_status\":{\"state\":\"sent\"}}," + json.Substring(1);
        json = json.Substring(0, json.Length - 1) + ", broken tail";

        SessionRecord found = Assert.IsType<SessionRecord>(Find(_root, Document,
            _ => new MemoryStream(Encoding.UTF8.GetBytes(json))));
        Assert.Equal("FICT-session", found.ChatId);
        Assert.Equal("not_sent", found.ModelStatus);
        Assert.Equal(folder, found.RunDirectory);
    }

    [Fact]
    public void AStatusBeyond65536BytesOffersNothingAndNoReadPassesTheCap()
    {
        Save("20261012-120000-FICT-Part");
        string json = "{\"session_id\":\"FICT-session\",\"padding\":\"" + new string('x', 65536)
            + "\",\"model_status\":{\"state\":\"not_sent\"}}";
        var stream = new BoundedHead(Encoding.UTF8.GetBytes(json));

        Assert.Null(Find(_root, Document, _ => stream));
        Assert.Equal(65536, stream.BytesRead);
        Assert.False(stream.AttemptedPastCap);
        Assert.True(stream.Disposed);
    }

    [Fact]
    public void MissingInvalidAndUnreadableRootsAndUnreadableFilesOfferNothing()
    {
        Assert.Null(Find(null, Document));
        Assert.Null(Find(Path.Combine(_root, "FICT-missing"), Document));
        Assert.Null(Find("\0FICT-invalid", Document));
        string fileRoot = Path.Combine(_root, "FICT-root-is-a-file");
        File.WriteAllText(fileRoot, "FICT");
        Assert.Null(Find(fileRoot, Document));
        Save("20261012-120000-FICT-Part");
        Assert.Null(Find(_root, Document, _ => throw new UnauthorizedAccessException("FICT denied")));
        Assert.Null(Find(_root, Document, _ => throw new IOException("FICT unreadable")));
        Assert.Null(Find(_root, Document, _ => new UnreadableHead()));
    }

    [Fact]
    public void FiveHundredReviewFoldersOpenExactlyOneHeadAndSearchWithinTwoSeconds()
    {
        string newest = string.Empty;
        for (int index = 0; index < 500; index++)
        {
            string stamp = new DateTime(2026, 10, 12, 12, 0, 0).AddSeconds(index)
                .ToString("yyyyMMdd-HHmmss", CultureInfo.InvariantCulture);
            newest = Save(stamp + "-FICT-Part");
        }
        int opens = 0;
        Stopwatch watch = Stopwatch.StartNew();

        SessionRecord? found = Find(_root, Document, path =>
        {
            opens++;
            Assert.Equal(Path.Combine(newest, "session.json"), path);
            return File.OpenRead(path);
        });
        watch.Stop();

        Assert.NotNull(found);
        Assert.Equal(newest, found!.RunDirectory);
        Assert.Equal(1, opens);
        Assert.True(watch.Elapsed < TimeSpan.FromSeconds(2), "FICT 500-folder search took " + watch.Elapsed);
    }

    [Fact]
    public void TheBackendsOwnSavedRecordIsReadByTheHeadReader()
    {
        // T102's fixture: the not-sent record as the backend's own `save_session` wrote it,
        // copied beside the tests by the project's `Fixtures/review-*.json` Content item.
        string fixture = Path.Combine(AppContext.BaseDirectory, "Fixtures", "review-not-sent-session.json");
        Assert.True(File.Exists(fixture), "review-not-sent-session.json was not copied next to the test assembly; "
            + "regenerate it with `uv run python tests/fixtures/pane/generate_waiting_fixtures.py --write` from reviewer/.");
        var document = new PageDocument(@"C:\FictionalVault\Vault\FICT-7000.SLDASM", "Default");
        string folder = RunFolders.CreateForDocument(_root, document.Path, new DateTime(2026, 10, 9, 12, 0, 0));
        File.Copy(fixture, Path.Combine(folder, "session.json"));

        JsonElement status = Assert.IsType<JsonElement>(RunFolders.ReadModelStatus(folder));
        SessionRecord found = Assert.IsType<SessionRecord>(Find(_root, document));

        Assert.Equal("not_sent", status.GetProperty("state").GetString());
        Assert.Equal(folder, found.RunDirectory);
        Assert.Equal("00000000-0000-4000-8000-000000000002", found.ChatId);
        Assert.Equal("not_sent", found.ModelStatus);
        Assert.Equal(document.Path, found.Document!.Path);
        Assert.Equal("Default", found.Document.Configuration);
        Assert.Equal(new DateTimeOffset(2026, 10, 9, 12, 0, 0, TimeSpan.Zero), found.StartedAt);
    }

    private string Save(string name, string state = "not_sent", string? path = null, string configuration = "FICT-Default")
    {
        string folder = Path.Combine(_root, name);
        Directory.CreateDirectory(folder);
        File.WriteAllText(Path.Combine(folder, "session.json"), Session(state, path ?? Document.Path, configuration));
        return folder;
    }

    private static string Session(string state, string path, string configuration) => JsonSerializer.Serialize(new
    {
        session_id = "FICT-session",
        model_status = new { state, document = new { path, configuration }, checked_at = CheckedAt },
    });

    private static SessionRecord? Find(string? root, PageDocument document, Func<string, Stream>? openHead = null) =>
        RunFolders.FindNotSentReview(root, document, openHead);

    private sealed class UnreadableHead : MemoryStream
    {
        public override int Read(byte[] buffer, int offset, int count) => throw new IOException("FICT interrupted read");
    }

    private sealed class BoundedHead : MemoryStream
    {
        public BoundedHead(byte[] bytes) : base(bytes) { }
        public int BytesRead { get; private set; }
        public bool AttemptedPastCap { get; private set; }
        public bool Disposed { get; private set; }
        public override int Read(byte[] buffer, int offset, int count)
        {
            if (count > 65536 - BytesRead) AttemptedPastCap = true;
            Assert.True(count <= 65536 - BytesRead, "the head read passed 65536 bytes");
            int read = base.Read(buffer, offset, Math.Min(count, 257));
            BytesRead += read;
            return read;
        }
        protected override void Dispose(bool disposing) { Disposed = true; base.Dispose(disposing); }
    }
}
