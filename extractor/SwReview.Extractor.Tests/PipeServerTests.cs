using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Console.Serve;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T072, the transport half: the real pipe loop, in this process, against a fake dispatcher.
///
/// What is worth proving here is the framing and the threading, not the commands (those are
/// in <see cref="BridgeDispatcherTests"/>): one line in gives exactly one line out, several
/// requests on one connection are answered in order, a malformed line does not kill the
/// connection, and the dispatcher is built once on an STA thread with every request running
/// on that same thread - which is the entire reason this class exists (research R3).
/// </summary>
public class PipeServerTests
{
    private static readonly TimeSpan Patience = TimeSpan.FromSeconds(20);

    [Fact]
    public void Run_AnswersOneLinePerRequest()
    {
        EchoDispatcher? dispatcher = null;

        WithServer(() => dispatcher = new EchoDispatcher(), client =>
        {
            string response = Ask(client, "{\"id\":\"1\",\"command\":\"ping\"}");

            using (JsonDocument parsed = JsonDocument.Parse(response))
            {
                Assert.Equal("1", parsed.RootElement.GetProperty("id").GetString());
                Assert.Equal("ok", parsed.RootElement.GetProperty("status").GetString());
            }
        });

        Assert.Single(dispatcher!.Handled);
    }

    [Fact]
    public void Run_AnswersSeveralRequestsOnOneConnectionInOrder()
    {
        EchoDispatcher? dispatcher = null;

        WithServer(() => dispatcher = new EchoDispatcher(), client =>
        {
            var ids = new List<string>();
            for (int i = 1; i <= 5; i++)
            {
                string response = Ask(client, $"{{\"id\":\"{i}\",\"command\":\"ping\"}}");
                using (JsonDocument parsed = JsonDocument.Parse(response))
                {
                    ids.Add(parsed.RootElement.GetProperty("id").GetString()!);
                }
            }

            Assert.Equal(new[] { "1", "2", "3", "4", "5" }, ids);
        });

        Assert.Equal(new[] { "1", "2", "3", "4", "5" }, dispatcher!.Handled);
    }

    [Fact]
    public void Run_MalformedLine_IsAnsweredAndTheConnectionSurvives()
    {
        EchoDispatcher? dispatcher = null;

        WithServer(() => dispatcher = new EchoDispatcher(), client =>
        {
            string bad = Ask(client, "this is not json");
            using (JsonDocument parsed = JsonDocument.Parse(bad))
            {
                Assert.Equal("error", parsed.RootElement.GetProperty("status").GetString());

                // Nothing identified the request, so the id is empty rather than invented.
                Assert.Equal(string.Empty, parsed.RootElement.GetProperty("id").GetString());
            }

            string good = Ask(client, "{\"id\":\"2\",\"command\":\"ping\"}");
            using (JsonDocument parsed = JsonDocument.Parse(good))
            {
                Assert.Equal("ok", parsed.RootElement.GetProperty("status").GetString());
            }
        });

        // The malformed line never reached the worker.
        Assert.Equal(new[] { "2" }, dispatcher!.Handled);
    }

    [Fact]
    public void Run_BlankLinesAreIgnored()
    {
        EchoDispatcher? dispatcher = null;

        WithServer(() => dispatcher = new EchoDispatcher(), client =>
        {
            client.Writer.WriteLine(string.Empty);
            client.Writer.WriteLine("   ");
            string response = Ask(client, "{\"id\":\"1\",\"command\":\"ping\"}");

            using (JsonDocument parsed = JsonDocument.Parse(response))
            {
                Assert.Equal("1", parsed.RootElement.GetProperty("id").GetString());
            }
        });

        Assert.Single(dispatcher!.Handled);
    }

    [Fact]
    public void Run_EveryRequestRunsOnTheOneStaThreadThatBuiltTheDispatcher()
    {
        // The whole point of the class: COM pointers are bound to the thread that made them,
        // so the dispatcher must be constructed on the worker and never called from anywhere
        // else (research R3, constitution Technical Constraints).
        var builds = 0;
        EchoDispatcher? dispatcher = null;

        WithServer(
            () =>
            {
                builds++;
                return dispatcher = new EchoDispatcher();
            },
            client =>
            {
                for (int i = 1; i <= 3; i++)
                {
                    Ask(client, $"{{\"id\":\"{i}\",\"command\":\"ping\"}}");
                }
            });

        Assert.Equal(1, builds);
        Assert.Equal(ApartmentState.STA, dispatcher!.BuiltOnApartment);
        Assert.Equal(3, dispatcher.HandledOnThread.Count);
        Assert.All(dispatcher.HandledOnThread, id => Assert.Equal(dispatcher.BuiltOnThread, id));
    }

    [Fact]
    public void Run_DispatcherThatThrows_StillAnswers()
    {
        // A worker that died would hang every later call instead of failing one.
        WithServer(() => new ThrowingDispatcher(), client =>
        {
            string response = Ask(client, "{\"id\":\"1\",\"command\":\"ping\"}");

            using (JsonDocument parsed = JsonDocument.Parse(response))
            {
                Assert.Equal("error", parsed.RootElement.GetProperty("status").GetString());
                Assert.Contains(
                    "the dispatcher exploded",
                    parsed.RootElement.GetProperty("error").GetString()!,
                    StringComparison.Ordinal);
            }

            Assert.Contains(
                "\"status\":\"error\"",
                Ask(client, "{\"id\":\"2\",\"command\":\"ping\"}"),
                StringComparison.Ordinal);
        });
    }

    [Fact]
    public void Start_WorkerThatCannotAttach_FailsBeforeAClientConnects()
    {
        using (var server = new PipeServer(
            NewPipeName(),
            () => throw new InvalidOperationException("SOLIDWORKS is not installed")))
        {
            InvalidOperationException error = Assert.Throws<InvalidOperationException>(
                () => server.Start());

            Assert.Contains("not installed", error.Message, StringComparison.Ordinal);
        }
    }

    [Fact]
    public void Constructor_BlankPipeName_Throws()
    {
        Assert.Throws<ArgumentException>(() => new PipeServer("  ", () => new ThrowingDispatcher()));
        Assert.Throws<ArgumentNullException>(() => new PipeServer("swreview", null!));
    }

    // ---- harness -----------------------------------------------------------------

    /// <summary>
    /// Runs a real <see cref="PipeServer"/> on a background thread, connects a real
    /// <see cref="NamedPipeClientStream"/> to it, and shuts both down afterwards. The
    /// dispatcher is built by the server, on its own thread, exactly as in production.
    /// </summary>
    private static void WithServer(Func<IBridgeDispatcher> factory, Action<Client> body)
    {
        string pipeName = NewPipeName();

        using (var stopping = new CancellationTokenSource())
        using (var server = new PipeServer(pipeName, factory))
        {
            Task serving = Task.Run(() => server.Run(stopping.Token));

            try
            {
                using (var pipe = new NamedPipeClientStream(".", pipeName, PipeDirection.InOut))
                {
                    pipe.Connect((int)Patience.TotalMilliseconds);
                    using (var client = new Client(pipe))
                    {
                        body(client);
                    }
                }
            }
            finally
            {
                // The accept loop is blocked waiting for the next client; the token releases it.
                stopping.Cancel();
                serving.Wait(Patience);
            }
        }
    }

    private static string Ask(Client client, string line)
    {
        client.Writer.WriteLine(line);
        string? response = client.Reader.ReadLine();
        Assert.NotNull(response);
        return response!;
    }

    private static string NewPipeName() => "swreview-test-" + Guid.NewGuid().ToString("N");

    private sealed class Client : IDisposable
    {
        public Client(Stream stream)
        {
            var encoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);
            Reader = new StreamReader(stream, encoding, false, 4096, leaveOpen: true);
            Writer = new StreamWriter(stream, encoding, 4096, leaveOpen: true)
            {
                AutoFlush = true,
                NewLine = "\n",
            };
        }

        public StreamReader Reader { get; }

        public StreamWriter Writer { get; }

        public void Dispose()
        {
            Writer.Dispose();
            Reader.Dispose();
        }
    }

    /// <summary>Answers everything with ok, and records which thread built and ran it.</summary>
    private sealed class EchoDispatcher : IBridgeDispatcher
    {
        public EchoDispatcher()
        {
            BuiltOnThread = Thread.CurrentThread.ManagedThreadId;
            BuiltOnApartment = Thread.CurrentThread.GetApartmentState();
        }

        public int BuiltOnThread { get; }

        public ApartmentState BuiltOnApartment { get; }

        public List<string> Handled { get; } = new List<string>();

        public List<int> HandledOnThread { get; } = new List<int>();

        public BridgeResponse Dispatch(BridgeRequest request)
        {
            // Only ever touched by the one worker thread, so no lock is needed - and if that
            // ever stopped being true, the assertions above would catch it.
            Handled.Add(request.Id);
            HandledOnThread.Add(Thread.CurrentThread.ManagedThreadId);
            return BridgeResponse.Ok(request.Id, null);
        }
    }

    private sealed class ThrowingDispatcher : IBridgeDispatcher
    {
        public BridgeResponse Dispatch(BridgeRequest request) =>
            throw new InvalidOperationException("the dispatcher exploded");
    }
}
