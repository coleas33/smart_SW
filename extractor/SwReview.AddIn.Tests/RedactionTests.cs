using System;
using System.Collections.Generic;
using System.Text.Encodings.Web;
using System.Text.Json;
using SwReview.AddIn.Settings;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T027: no configured secret reaches a log line, an error message or the pane.
///
/// A literal substring replacement is not enough on its own. The text we have to scrub is
/// usually an SDK or HTTP error that echoes the request it failed on, and by then the key has
/// been through an encoder: a query string carries it percent-encoded, and a JSON request body
/// carries it with System.Text.Json's default escaping, which rewrites `+` and `=` as their
/// six-character JSON code-point escapes. Each encoded form is a distinct string that still
/// discloses the key, so Redaction masks the encoded forms as well as the literal one.
/// </summary>
public sealed class RedactionTests
{
    private const string Key = "sk-proj-EXAMPLE/abc+def=0123456789";

    [Fact]
    public void MaskIsTheSameTokenThePythonSideUses()
    {
        // reviewer/src/swreview/agent/settings.py MASK: the pane shows text from both sides.
        Assert.Equal("[redacted]", Redaction.Mask);
    }

    [Fact]
    public void MasksTheLiteralSecretInALogLine()
    {
        string line = $"POST /v1/responses failed: Authorization: Bearer {Key} (401)";

        string redacted = Redaction.Redact(line, new[] { Key });

        Assert.DoesNotContain(Key, redacted, StringComparison.Ordinal);
        Assert.Equal("POST /v1/responses failed: Authorization: Bearer [redacted] (401)", redacted);
    }

    [Fact]
    public void MasksEveryOccurrenceOfEverySecret()
    {
        const string second = "swreview-bridge-secret";
        string line = $"{Key} then {second} then {Key}";

        string redacted = Redaction.Redact(line, new[] { Key, second });

        Assert.Equal("[redacted] then [redacted] then [redacted]", redacted);
    }

    [Fact]
    public void MasksTheUrlEncodedForm()
    {
        string encoded = Uri.EscapeDataString(Key);
        Assert.NotEqual(Key, encoded); // the test would be vacuous if the key needed no encoding
        string line = $"GET https://api.example.invalid/models?key={encoded} -> 401";

        string redacted = Redaction.Redact(line, new[] { Key });

        Assert.DoesNotContain(encoded, redacted, StringComparison.Ordinal);
        Assert.Contains("[redacted]", redacted, StringComparison.Ordinal);
    }

    [Fact]
    public void MasksTheUrlEncodedFormWithLowercaseHex()
    {
        // Uri.EscapeDataString writes upper-case hex; encodeURIComponent-style helpers in other
        // stacks write lower-case, and both forms disclose the key.
        string encoded = Uri.EscapeDataString(Key)
            .Replace("%2F", "%2f")
            .Replace("%2B", "%2b")
            .Replace("%3D", "%3d");
        string line = $"GET https://api.example.invalid/models?key={encoded} -> 401";

        string redacted = Redaction.Redact(line, new[] { Key });

        Assert.DoesNotContain(encoded, redacted, StringComparison.Ordinal);
        Assert.Contains("[redacted]", redacted, StringComparison.Ordinal);
    }

    [Fact]
    public void MasksTheJsonEscapedFormWrittenByTheDefaultEncoder()
    {
        string body = JsonSerializer.Serialize(new Dictionary<string, string> { { "api_key", Key } });
        Assert.DoesNotContain(Key, body, StringComparison.Ordinal); // `+` and `=` are escaped

        string redacted = Redaction.Redact($"request body was {body}", new[] { Key });

        Assert.Contains("[redacted]", redacted, StringComparison.Ordinal);
        Assert.DoesNotContain("0123456789", redacted, StringComparison.Ordinal);
    }

    [Fact]
    public void MasksTheJsonEscapedFormWrittenByTheRelaxedEncoder()
    {
        var options = new JsonSerializerOptions { Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };
        string body = JsonSerializer.Serialize(
            new Dictionary<string, string> { { "api_key", Key } }, options);

        string redacted = Redaction.Redact($"request body was {body}", new[] { Key });

        Assert.Contains("[redacted]", redacted, StringComparison.Ordinal);
        Assert.DoesNotContain("0123456789", redacted, StringComparison.Ordinal);
    }

    [Fact]
    public void MasksAJsonEscapedSecretContainingQuotesAndBackslashes()
    {
        const string awkward = "secret\"with\\backslash";
        string body = JsonSerializer.Serialize(new Dictionary<string, string> { { "token", awkward } });

        string redacted = Redaction.Redact(body, new[] { awkward });

        Assert.DoesNotContain("backslash", redacted, StringComparison.Ordinal);
        Assert.Contains("[redacted]", redacted, StringComparison.Ordinal);
    }

    [Fact]
    public void MasksTheLongestSecretFirstSoNoTailSurvives()
    {
        // A prefix and the full key are both configured; replacing the prefix first would
        // leave "[redacted]def0123456789" in the log.
        const string prefix = "sk-proj-EXAMPLE";

        string redacted = Redaction.Redact(Key, new[] { prefix, Key });

        Assert.Equal("[redacted]", redacted);
    }

    [Fact]
    public void MasksExceptionMessagesIncludingInnerExceptions()
    {
        var inner = new InvalidOperationException($"bad key {Key}");
        var outer = new InvalidOperationException($"provider call failed for {Key}", inner);

        string redacted = Redaction.Redact(outer, new[] { Key });

        Assert.DoesNotContain(Key, redacted, StringComparison.Ordinal);
        Assert.Contains("provider call failed for [redacted]", redacted, StringComparison.Ordinal);
        Assert.Contains("bad key [redacted]", redacted, StringComparison.Ordinal);
    }

    [Fact]
    public void MasksTheEncodedFormsInsideAnExceptionMessage()
    {
        var error = new InvalidOperationException(
            $"GET https://api.example.invalid/v1?key={Uri.EscapeDataString(Key)} returned 401");

        string redacted = Redaction.Redact(error, new[] { Key });

        Assert.DoesNotContain("0123456789", redacted, StringComparison.Ordinal);
    }

    [Fact]
    public void BlankAndNullSecretsAreIgnored()
    {
        const string line = "nothing secret here";

        string redacted = Redaction.Redact(line, new string?[] { null, string.Empty, "   " });

        Assert.Equal(line, redacted);
    }

    [Fact]
    public void TextWithoutASecretIsUnchanged()
    {
        const string line = "session 8f3a started with provider openai";

        Assert.Equal(line, Redaction.Redact(line, new[] { Key }));
    }

    [Fact]
    public void NullTextAndNullSecretsAreSafe()
    {
        Assert.Equal(string.Empty, Redaction.Redact((string?)null, new[] { Key }));
        Assert.Equal("text", Redaction.Redact("text", null));
        Assert.Equal(string.Empty, Redaction.Redact((Exception?)null, new[] { Key }));
    }
}
