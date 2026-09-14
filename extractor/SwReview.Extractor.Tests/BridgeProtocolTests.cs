using System;
using System.Text.Json;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Ir;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T072, the wire format half. One JSON object per line (research R3), so the framing is
/// the contract: a response that spans two lines would desynchronise the client for the
/// rest of the session.
///
/// Serve/PROTOCOL.md is the document these assertions hold to.
/// </summary>
public class BridgeProtocolTests
{
    [Fact]
    public void ReadRequest_ReadsIdCommandAndParams()
    {
        BridgeRequest request = BridgeCodec.ReadRequest(
            "{\"id\":\"7\",\"command\":\"capture\",\"params\":{\"persist_ref\":\"cmVm\",\"view\":\"iso\"}}");

        Assert.Equal("7", request.Id);
        Assert.Equal("capture", request.Command);
        Assert.Equal("cmVm", request.Params.GetProperty("persist_ref").GetString());
    }

    [Fact]
    public void ReadRequest_ParamsMayBeOmitted()
    {
        BridgeRequest request = BridgeCodec.ReadRequest("{\"id\":\"1\",\"command\":\"ping\"}");

        Assert.Equal(JsonValueKind.Undefined, request.Params.ValueKind);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("not json")]
    [InlineData("{\"command\":\"ping\"}")]
    [InlineData("{\"id\":\"1\"}")]
    [InlineData("{\"id\":\"\",\"command\":\"ping\"}")]
    public void ReadRequest_MalformedLine_Throws(string line)
    {
        Assert.Throws<BridgeProtocolError>(() => BridgeCodec.ReadRequest(line));
    }

    [Fact]
    public void ReadRequest_UnknownTopLevelField_Throws()
    {
        // The same additionalProperties: false stance the IR schema takes; drift fails loud.
        Assert.Throws<BridgeProtocolError>(() =>
            BridgeCodec.ReadRequest("{\"id\":\"1\",\"command\":\"ping\",\"extra\":true}"));
    }

    [Fact]
    public void ReadRequest_SecretIsOptionalAndAbsentMeansNull()
    {
        // The console host does not issue secrets, so a line without one still parses; the
        // policy, not the codec, decides whether that is allowed (T045).
        BridgeRequest request = BridgeCodec.ReadRequest("{\"id\":\"1\",\"command\":\"ping\"}");

        Assert.Null(request.Secret);
    }

    [Fact]
    public void ReadRequest_ReadsTheSecret()
    {
        BridgeRequest request = BridgeCodec.ReadRequest(
            "{\"id\":\"1\",\"command\":\"ping\",\"secret\":\"per-launch\"}");

        Assert.Equal("per-launch", request.Secret);
    }

    [Fact]
    public void WriteResponse_NeverCarriesASecret()
    {
        // A response is written to a log and to a page; the secret must not ride along.
        string line = BridgeCodec.WriteResponse(
            BridgeResponse.Failed("1", SwBridgeDispatcher.UnauthorizedError));

        Assert.DoesNotContain("secret", line, StringComparison.Ordinal);
        Assert.Contains("\"error\":\"unauthorized\"", line, StringComparison.Ordinal);
    }

    [Fact]
    public void WriteResponse_IsExactlyOneLine()
    {
        string line = BridgeCodec.WriteResponse(BridgeResponse.Ok(
            "1",
            new InterferenceCommandResult
            {
                Interferences =
                {
                    new Ir.Interference
                    {
                        Id = "int:0001",
                        Configuration = "Default",
                        ComponentIds = { "cmp:0001", "cmp:0002" },
                        Volume = new Volume(3.2e-9, VolumeUnit.M3),
                        GroupKey = "cmp:0001|cmp:0002",
                    },
                },
            }));

        Assert.DoesNotContain("\n", line, StringComparison.Ordinal);
        Assert.DoesNotContain("\r", line, StringComparison.Ordinal);
    }

    [Fact]
    public void WriteResponse_CarriesTheEnvelopeFieldsProtocolMdNames()
    {
        string line = BridgeCodec.WriteResponse(
            new BridgeResponse { Id = "3", Status = BridgeStatus.Error, Error = "no", ElapsedMs = 42 });

        using (JsonDocument parsed = JsonDocument.Parse(line))
        {
            JsonElement root = parsed.RootElement;
            Assert.Equal("3", root.GetProperty("id").GetString());
            Assert.Equal("error", root.GetProperty("status").GetString());
            Assert.Equal(JsonValueKind.Null, root.GetProperty("result").ValueKind);
            Assert.Equal("no", root.GetProperty("error").GetString());
            Assert.Equal(42, root.GetProperty("elapsed_ms").GetInt64());
        }
    }

    [Fact]
    public void WriteResponse_EnumsUseTheSameStringsPackageJsonUses()
    {
        // An Interference that travels over the bridge must be byte-identical to one that
        // was dumped to a file, or the reviewer would need two parsers.
        string line = BridgeCodec.WriteResponse(BridgeResponse.Ok(
            "1",
            new InterferenceCommandResult
            {
                Interferences =
                {
                    new Ir.Interference
                    {
                        Id = "int:0001",
                        Status = InterferenceStatus.Truncated,
                        Volume = new Volume(1.0, VolumeUnit.M3),
                        ComponentIds = { "cmp:0001", "cmp:0002" },
                    },
                },
                Gaps = { new Gap { Kind = GapKind.NotExtracted, EntityKind = "interference", Reason = "why" } },
            }));

        Assert.Contains("\"status\":\"truncated\"", line, StringComparison.Ordinal);
        Assert.Contains("\"unit\":\"m3\"", line, StringComparison.Ordinal);
        Assert.Contains("\"kind\":\"not_extracted\"", line, StringComparison.Ordinal);
        Assert.Contains("\"fastener_folder_treatment\":\"include\"", line, StringComparison.Ordinal);
    }

    [Fact]
    public void WriteResponse_NullsAreWrittenNotSkipped()
    {
        // "unknown" has to survive the trip, exactly as it does in package.json.
        string line = BridgeCodec.WriteResponse(BridgeResponse.Ok("1", null));

        Assert.Contains("\"result\":null", line, StringComparison.Ordinal);
        Assert.Contains("\"error\":null", line, StringComparison.Ordinal);
    }

    [Fact]
    public void WriteResponse_Base64PersistRefsStayReadable()
    {
        string line = BridgeCodec.WriteResponse(BridgeResponse.Ok(
            "1",
            new CaptureCommandResult
            {
                Capture = new Ir.Capture { Id = "cap:0001", PersistRef = "a+b/c=", File = "captures/cap-0001.png" },
            }));

        Assert.Contains("a+b/c=", line, StringComparison.Ordinal);
    }

    [Fact]
    public void WriteResponse_NullResponse_Throws()
    {
        Assert.Throws<ArgumentNullException>(() => BridgeCodec.WriteResponse(null!));
    }
}
