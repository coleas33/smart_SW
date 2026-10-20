using System;
using System.IO;
using System.Net;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using SwReview.AddIn.Review;
using Xunit;

namespace SwReview.AddIn.Tests;

[Collection(StubChildrenCollection.Name)]
public sealed class BackendClientSessionBodyTests
{
    [Theory]
    [InlineData(ReviewMode.Send, true, false)]
    [InlineData(ReviewMode.Wait, false, false)]
    [InlineData(ReviewMode.Recheck, false, true)]
    public async Task TheModeTravelsAsTheTwoBooleanFieldsOnTheWire(ReviewMode mode, bool send, bool recheck)
    {
        JsonElement body = await Posted(Request(mode));
        Assert.Equal(send, body.GetProperty("send_when_checked").GetBoolean());
        Assert.Equal(recheck, body.GetProperty("recheck").GetBoolean());
        Assert.Equal(@"C:\Fictional\FICT-run", body.GetProperty("run_dir").GetString());
        Assert.False(body.TryGetProperty("engineering_context", out _));
    }

    /// <summary>
    /// Owner decision 99A: an unticked context review posts `send_when_checked: false` beside its
    /// attachment, so the backend waits with nothing sent.
    /// </summary>
    [Fact]
    public async Task AnUntickedContextReviewPostsTheWaitModeBesideItsAttachment()
    {
        string contextId = Guid.NewGuid().ToString();
        JsonElement body = await Posted(new NewSessionRequest(
            @"C:\Fictional\FICT-run", "openai", "fictional", "high", "FICT-engineer", null, null,
            mode: ReviewMode.Wait,
            engineeringContext: new EngineeringContextAttachment(contextId, new string('a', 64), new string('b', 64))));
        Assert.False(body.GetProperty("send_when_checked").GetBoolean());
        Assert.False(body.GetProperty("recheck").GetBoolean());
        JsonElement attachment = body.GetProperty("engineering_context");
        Assert.Equal(contextId, attachment.GetProperty("context_id").GetString());
        Assert.Equal(new string('a', 64), attachment.GetProperty("head_digest").GetString());
        Assert.Equal(new string('b', 64), attachment.GetProperty("package_sha256").GetString());
    }

    /// <summary>Posts `request` through the real client to a loopback listener; returns the body.</summary>
    private static async Task<JsonElement> Posted(NewSessionRequest request)
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
                ChatSessionHandle handle = client.CreateSession(request);
                Assert.Equal("chat-1", handle.ChatId);
                Assert.Same(received, await Task.WhenAny(received, Task.Delay(TimeSpan.FromSeconds(5))));
                var wire = await received;
                Assert.Equal("POST", wire.method);
                Assert.Equal("/sessions", wire.path);
                Assert.Equal("Bearer " + StubBackend.DefaultToken, wire.authorization);
                using (JsonDocument body = JsonDocument.Parse(wire.body)) return body.RootElement.Clone();
            }
        }
    }

    [Fact]
    public void EveryModeUsesTheThirtySecondCallTimeoutWithoutWaiting()
    {
        const BindingFlags staticMembers = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
        Type client = typeof(BackendClient);
        FieldInfo timeout = Assert.IsAssignableFrom<FieldInfo>(client.GetField("CallTimeout", staticMembers));
        Assert.Equal(TimeSpan.FromSeconds(30), Assert.IsType<TimeSpan>(timeout.GetValue(null)));
        Assert.Null(client.GetField("ChecksOnlyTimeout", staticMembers));
        Assert.Null(client.GetMethod("TimeoutFor", staticMembers));

        // The wire theory exercises Send, Wait and Recheck through this one call path.
        // With no timeout argument, all three use the same 30-second bound.
        MethodInfo call = Assert.IsAssignableFrom<MethodInfo>(client.GetMethod("Call", BindingFlags.Instance | BindingFlags.NonPublic));
        Assert.Collection(call.GetParameters(),
            parameter => Assert.Equal(typeof(string), parameter.ParameterType),
            parameter => Assert.Equal(typeof(string), parameter.ParameterType),
            parameter => Assert.Equal(typeof(string), parameter.ParameterType));
        Assert.Equal(ReviewMode.Send, new NewSessionRequest("run", "openai", "fictional", "high", "FICT-engineer", null, null).Mode);
    }

    private static NewSessionRequest Request(ReviewMode mode) => new NewSessionRequest(
        @"C:\Fictional\FICT-run", "openai", "fictional", "high", "FICT-engineer", null, null, mode: mode);
}
