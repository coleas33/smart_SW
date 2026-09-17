using System;
using System.Globalization;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;

namespace SwReview.AddIn.Review;

/// <summary>
/// Reads `GET /sessions/{chat_id}/events` in the host and hands each raw SSE frame to whoever
/// owns it - <see cref="ReviewHost"/>, which posts it to the page as `events.frame`.
///
/// <b>Why the host reads it.</b> This is the one backend route the same-origin proxy cannot
/// serve (<see cref="BackendProxy"/>): a `WebResourceRequested` response must have all of its
/// content available when the deferral completes, and WebView2 reads every response stream on
/// one background thread, so a stream that stays open would stall every other request in the
/// control. A request made by the add-in's own C# code is also the one kind the pilot
/// workstation's web filter does not intercept, which is the whole reason this class exists
/// (`docs/pane-backend-proxy.md`).
///
/// <b>What it does not do.</b> It does not parse. A frame is passed on as the text between
/// blank lines, because the page already has a parser that reads `id:` and `data:` and tracks
/// `seq`, and two parsers that can disagree about what an event is would be one too many. It
/// does not reconnect either: the page owns the backoff and the `Last-Event-ID` it reopens
/// with, because the page is the thing that knows what it has already shown.
///
/// <b>One reader at a time.</b> Every <see cref="Open"/> stops the reader before it, and a
/// generation counter - not the thread's liveness - decides whether a frame still belongs to
/// anyone. A socket read does not end the moment the request is aborted, so a frame can arrive
/// from a stream that has already been replaced; it is dropped rather than delivered into the
/// transcript of a different chat.
/// </summary>
public sealed class EventStreamPump : IDisposable
{
    /// <summary>How long the reader waits for the response head. The body is unbounded.</summary>
    private static readonly TimeSpan ConnectTimeout = TimeSpan.FromSeconds(30);

    /// <summary>How long <see cref="Close"/> waits for a reader to notice its abort.</summary>
    private static readonly TimeSpan StopTimeout = TimeSpan.FromSeconds(5);

    private readonly Func<BackendEndpoint?> _endpoint;
    private readonly Action<string, string> _onFrame;
    private readonly Action<string, string> _onClosed;
    private readonly object _gate = new object();

    private Thread? _reader;
    private HttpWebRequest? _request;
    private int _generation;
    private bool _disposed;

    /// <param name="endpoint">Where the backend is listening, asked for per open.</param>
    /// <param name="onFrame">`(chat_id, frame)` for each frame, on the reader thread.</param>
    /// <param name="onClosed">`(chat_id, reason)` once, when the stream ends or fails.</param>
    public EventStreamPump(
        Func<BackendEndpoint?> endpoint,
        Action<string, string> onFrame,
        Action<string, string> onClosed)
    {
        _endpoint = endpoint ?? throw new ArgumentNullException(nameof(endpoint));
        _onFrame = onFrame ?? throw new ArgumentNullException(nameof(onFrame));
        _onClosed = onClosed ?? throw new ArgumentNullException(nameof(onClosed));
    }

    /// <summary>
    /// Starts reading this chat's stream, stopping any stream already being read.
    /// </summary>
    /// <param name="chatId">The chat to read; it travels in the path, never the token.</param>
    /// <param name="lastEventId">The highest `seq` the page has shown, or null for a first
    /// connection: the backend replays from `events.jsonl` after it and nothing before it.</param>
    public void Open(string chatId, string? lastEventId)
    {
        if (chatId == null)
        {
            throw new ArgumentNullException(nameof(chatId));
        }

        Close();

        int generation;
        lock (_gate)
        {
            if (_disposed)
            {
                return;
            }

            generation = ++_generation;
            _reader = new Thread(() => Read(chatId, lastEventId, generation))
            {
                IsBackground = true,
                Name = "swreview-event-stream",
            };
            _reader.Start();
        }
    }

    /// <summary>
    /// Stops the reader: the request is aborted so a blocking read returns, and the thread is
    /// joined within a bound. Silent - a stream the host stopped is not something the page needs
    /// to be told about, because the page is what asked.
    /// </summary>
    public void Close()
    {
        Thread? reader;
        HttpWebRequest? request;

        lock (_gate)
        {
            // Bumped first: a frame the reader is mid-delivery of belongs to a generation that
            // no longer exists the moment this returns.
            _generation++;
            reader = _reader;
            request = _request;
            _reader = null;
            _request = null;
        }

        if (request != null)
        {
            try
            {
                request.Abort();
            }
            catch (Exception)
            {
                // Already finished; the join below is the only thing left to do.
            }
        }

        if (reader != null && reader != Thread.CurrentThread)
        {
            // Bounded: a reader wedged in a socket read must not hold up the pane's shutdown,
            // and it is a background thread either way.
            reader.Join(StopTimeout);
        }
    }

    public void Dispose()
    {
        Close();
        lock (_gate)
        {
            _disposed = true;
        }
    }

    private void Read(string chatId, string? lastEventId, int generation)
    {
        try
        {
            BackendEndpoint? endpoint = _endpoint();
            if (endpoint == null)
            {
                Closed(generation, chatId, "the review backend is not running.");
                return;
            }

            HttpWebRequest request = Build(endpoint, chatId, lastEventId);
            lock (_gate)
            {
                if (generation != _generation)
                {
                    return;
                }

                _request = request;
            }

            using (var response = (HttpWebResponse)request.GetResponse())
            using (Stream? stream = response.GetResponseStream())
            {
                if (stream == null)
                {
                    Closed(generation, chatId, "the event stream carried no body.");
                    return;
                }

                Drain(stream, chatId, generation);
            }

            Closed(generation, chatId, "the backend closed the event stream.");
        }
        catch (Exception failure)
        {
            // An abort from `Close` lands here too; `Closed` drops it, because the generation it
            // belonged to is gone.
            Closed(generation, chatId, failure.Message);
        }
    }

    private HttpWebRequest Build(BackendEndpoint endpoint, string chatId, string? lastEventId)
    {
        var request = (HttpWebRequest)WebRequest.Create(new Uri(
            string.Format(
                CultureInfo.InvariantCulture,
                "http://127.0.0.1:{0}/sessions/{1}/events",
                endpoint.Port,
                Uri.EscapeDataString(chatId)),
            UriKind.Absolute));

        request.Method = "GET";
        request.Accept = "text/event-stream";

        // The token is a header and never a URL: a URL reaches access logs, WebView2's history
        // and every crash dump (chat-api.md).
        request.Headers["Authorization"] = "Bearer " + endpoint.Token;
        if (!string.IsNullOrEmpty(lastEventId))
        {
            request.Headers["Last-Event-ID"] = lastEventId;
        }

        // The corporate proxy must not be consulted for 127.0.0.1; on the pilot workstation it
        // is the interception that made the page's own fetches fail (BackendClient says the
        // same, for the same reason).
        request.Proxy = null;
        request.KeepAlive = true;

        // The head has a deadline; the body does not. A stream with nothing to say for an hour
        // is a review waiting on a slow provider, not a failure.
        request.Timeout = (int)ConnectTimeout.TotalMilliseconds;
        request.ReadWriteTimeout = Timeout.Infinite;
        request.AllowReadStreamBuffering = false;

        return request;
    }

    /// <summary>
    /// Splits the stream into frames on blank lines and hands each one on.
    ///
    /// Line by line rather than chunk by chunk because a chunk boundary falls wherever TCP put
    /// it: a frame arrives in two reads as often as in one, and a split frame reaches the page
    /// as two halves it cannot parse. The lines of a frame are rejoined with `\n`, which is what
    /// the page's parser splits on - it accepts either ending, so a `\r\n` server and an `\n`
    /// server reach it as the same frame. A trailing partial frame is dropped: the stream ended
    /// mid-frame, so there is no event in it to act on.
    /// </summary>
    private void Drain(Stream stream, string chatId, int generation)
    {
        var frame = new StringBuilder();

        using (var reader = new StreamReader(stream, Encoding.UTF8))
        {
            while (true)
            {
                string? line = reader.ReadLine();
                if (line == null)
                {
                    return;
                }

                if (line.Length > 0)
                {
                    if (frame.Length > 0)
                    {
                        frame.Append('\n');
                    }

                    frame.Append(line);
                    continue;
                }

                if (frame.Length == 0)
                {
                    // Consecutive blank lines: an SSE keep-alive, nothing to deliver.
                    continue;
                }

                string complete = frame.ToString();
                frame.Length = 0;
                if (!Deliver(generation, chatId, complete))
                {
                    return;
                }
            }
        }
    }

    /// <summary>One frame, unless this reader has been replaced. False means "stop reading".</summary>
    private bool Deliver(int generation, string chatId, string frame)
    {
        lock (_gate)
        {
            if (generation != _generation)
            {
                return false;
            }
        }

        _onFrame(chatId, frame);
        return true;
    }

    private void Closed(int generation, string chatId, string reason)
    {
        lock (_gate)
        {
            if (generation != _generation)
            {
                return;
            }

            // This reader is done; nothing is left for `Close` to abort or join.
            _reader = null;
            _request = null;
            _generation++;
        }

        _onClosed(chatId, reason);
    }
}
