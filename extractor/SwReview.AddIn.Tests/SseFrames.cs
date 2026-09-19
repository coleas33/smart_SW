using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.Web.WebView2.Core;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Server-sent event frames as the backend writes them and the host hands them to the page:
/// `id` is the `seq`, `event` is the `type`, `data` is the body alone (contracts/chat-api.md,
/// the events row; `_sse` in chat/server.py). One helper for every page test that plays the
/// host's side of the stream, so the wire shape lives in one place.
///
/// Until 2026-09-18 each page test fabricated its own frame, put a whole `{seq, type, body}`
/// envelope in `data` and sent no `event` line at all - bytes the backend never writes - and
/// the page's parser, which expected exactly that envelope, stayed green here while every
/// real frame fell through it on the workstation (docs/pane-findings-2026-09-18.md). The
/// contract sample below is the guard against a repeat: the Python producer test pins its
/// bytes and these tests feed the same bytes to the page, so the two ends cannot drift apart
/// without one suite going red.
/// </summary>
internal static class SseFrames
{
    /// <summary>
    /// `specs/002-task-pane-assistant/contracts/event-stream.sample.sse`, copied beside the
    /// tests by the csproj: the closing `turn.ended` / `session.ended` pair, byte for byte as
    /// `_sse` encodes it, pinned by tests/unit/test_chat_server.py.
    /// </summary>
    public const string ContractSample = "event-stream.sample.sse";

    /// <summary>A keep-alive comment: proof of the socket, not an event.</summary>
    public const string KeepAlive = ": ping - 2026-09-18T21:30:00";

    /// <summary>One frame, the text between blank lines, as <see cref="Review.EventStreamPump"/> assembles it.</summary>
    public static string Frame(int seq, string type, string body) =>
        "id: " + seq + "\nevent: " + type + "\ndata: " + body;

    /// <summary>
    /// The frames of the contract sample, split the way the pump splits a response: at
    /// blank lines, each line kept verbatim minus its terminator.
    /// </summary>
    public static IReadOnlyList<string> ContractSampleFrames()
    {
        string path = Path.Combine(AppContext.BaseDirectory, ContractSample);
        Assert.True(
            File.Exists(path),
            ContractSample + " was not copied next to the test assembly; check the Content item in the csproj.");

        var frames = new List<string>();
        var lines = new List<string>();
        foreach (string line in File.ReadAllText(path).Split(new[] { "\r\n", "\n" }, StringSplitOptions.None))
        {
            if (line.Length > 0)
            {
                lines.Add(line);
                continue;
            }

            if (lines.Count > 0)
            {
                frames.Add(string.Join("\n", lines));
                lines.Clear();
            }
        }

        Assert.NotEmpty(frames);
        return frames;
    }

    /// <summary>One `events.frame` from the host, as <see cref="Review.ReviewHost"/> posts what the pump read.</summary>
    public static Task<string> Push(CoreWebView2 page, string chatId, string frame)
    {
        page.PostWebMessageAsJson(JsonSerializer.Serialize(
            new { type = "events.frame", id = (string?)null, payload = new { chat_id = chatId, frame } }));
        return page.ExecuteScriptAsync("0");
    }
}
