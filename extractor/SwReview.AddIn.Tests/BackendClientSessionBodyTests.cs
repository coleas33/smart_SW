using System;
using System.IO;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using SwReview.AddIn.Review;
using Xunit;

namespace SwReview.AddIn.Tests;

public sealed class BackendClientSessionBodyTests
{
    [Theory]
    [InlineData(ReviewMode.Send, true, false)]
    [InlineData(ReviewMode.Wait, false, false)]
    [InlineData(ReviewMode.Recheck, false, true)]
    public async Task TheModeTravelsAsTheTwoBooleanFieldsOnTheWire(ReviewMode mode, bool send, bool recheck)
    {
        using (HttpListener listener = LoopbackPort.StartListener(out int port))
        using (var stub = new StubBackend())
        using (var supervisor = new BackendSupervisor(() => false))
        {
            stub.PrintsHandshake(port);
            var options = new BackendStartOptions(stub.Command, stub.LogPath)
            {
                RunRoot = stub.RunRoot,
                AllowOrigin = "https://swreview.invalid",
                HealthProbe = (origin, token) => true,
                StopGrace = TimeSpan.FromMilliseconds(100),
            };
            foreach (var knob in stub.Knobs) options.Environment[knob.Key] = knob.Value;
            supervisor.Start(options);
            Task<(string method, string path, string authorization, string body)> received = Task.Run(() =>
            {
                HttpListenerContext context = listener.GetContext();
                string body;
                using (var reader = new StreamReader(context.Request.InputStream, Encoding.UTF8)) body = reader.ReadToEnd();
                var request = (context.Request.HttpMethod, context.Request.Url!.AbsolutePath, context.Request.Headers["Authorization"]!, body);
                byte[] reply = Encoding.UTF8.GetBytes("{\"chat_id\":\"chat-1\",\"review_session_id\":\"review-1\",\"not_examined\":null}");
                context.Response.StatusCode = 201;
                context.Response.ContentLength64 = reply.Length;
                context.Response.OutputStream.Write(reply, 0, reply.Length);
                context.Response.Close();
                return request;
            });
            using (var client = new BackendClient(supervisor, Path.GetDirectoryName(stub.LogPath)!, null))
            {
                ChatSessionHandle handle = client.CreateSession(Request(mode));
                Assert.Equal("chat-1", handle.ChatId);
                Assert.Same(received, await Task.WhenAny(received, Task.Delay(TimeSpan.FromSeconds(5))));
                var wire = await received;
                Assert.Equal("POST", wire.method);
                Assert.Equal("/sessions", wire.path);
                Assert.Equal("Bearer " + StubBackend.DefaultToken, wire.authorization);
                using (JsonDocument body = JsonDocument.Parse(wire.body))
                {
                    Assert.Equal(send, body.RootElement.GetProperty("send_when_checked").GetBoolean());
                    Assert.Equal(recheck, body.RootElement.GetProperty("recheck").GetBoolean());
                    Assert.Equal(@"C:\Fictional\FICT-run", body.RootElement.GetProperty("run_dir").GetString());
                }
            }
        }
    }

    [Fact]
    public void TimeoutsSelectChecksOnlyForWaitOrRecheckWithoutWaiting()
    {
        Assert.Equal(TimeSpan.FromSeconds(30), BackendClient.TimeoutFor(null));
        Assert.Equal(BackendClient.TimeoutFor(null), BackendClient.ChecksOnlyTimeout);
        Assert.Equal(BackendClient.TimeoutFor(null), BackendClient.TimeoutFor(Request(ReviewMode.Send)));
        Assert.Equal(BackendClient.ChecksOnlyTimeout, BackendClient.TimeoutFor(Request(ReviewMode.Wait)));
        Assert.Equal(BackendClient.ChecksOnlyTimeout, BackendClient.TimeoutFor(Request(ReviewMode.Recheck)));
        Assert.Equal(ReviewMode.Send, new NewSessionRequest("run", "openai", "fictional", "high", "FICT-engineer", null, null).Mode);
    }

    private static NewSessionRequest Request(ReviewMode mode) => new NewSessionRequest(
        @"C:\Fictional\FICT-run", "openai", "fictional", "high", "FICT-engineer", null, null, mode: mode);
}
