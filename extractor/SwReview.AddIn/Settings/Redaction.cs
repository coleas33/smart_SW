using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;

namespace SwReview.AddIn.Settings;

/// <summary>
/// Masks configured secrets in anything headed for a human: a log line, an error shown in the
/// pane, a message sent to the page.
///
/// The mask is a substring replacement rather than a pattern, for the same reason the Python
/// side gives (reviewer/src/swreview/agent/settings.py): the thing that must not be printed is
/// known exactly, and guessing at key <i>shapes</i> would both miss real keys and mangle
/// innocent text. The one place a literal replacement is not enough is the case that actually
/// leaks keys - an SDK or HTTP error that echoes the request it failed on, where the key has
/// already been through an encoder. So every secret is masked in its literal form, its
/// percent-encoded form (upper- and lower-case hex), and both JSON-escaped forms
/// System.Text.Json can write: the default encoder rewrites `+` and the quote character as
/// their six-character JSON code-point escapes, while the relaxed encoder leaves `+` alone
/// and writes the quote with a backslash.
/// </summary>
public static class Redaction
{
    /// <summary>What a secret becomes. The same token the Python side writes, so a pane that
    /// shows text from both sides shows one thing.</summary>
    public const string Mask = "[redacted]";

    private static readonly JsonSerializerOptions DefaultEscaping = new JsonSerializerOptions();

    private static readonly JsonSerializerOptions RelaxedEscaping = new JsonSerializerOptions
    {
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };

    /// <summary>
    /// <paramref name="text"/> with every form of every secret replaced by <see cref="Mask"/>.
    /// </summary>
    /// <param name="text">The line to scrub; null or empty yields an empty string.</param>
    /// <param name="secrets">The configured secrets. Null, empty and whitespace entries are
    /// ignored - replacing an empty string would mask the whole line.</param>
    public static string Redact(string? text, IEnumerable<string?>? secrets)
    {
        if (string.IsNullOrEmpty(text))
        {
            return string.Empty;
        }

        if (secrets == null)
        {
            return text!;
        }

        var forms = new List<string>();
        foreach (string? secret in secrets)
        {
            if (string.IsNullOrWhiteSpace(secret))
            {
                continue;
            }

            foreach (string form in Variants(secret!))
            {
                if (form.Length > 0 && !forms.Contains(form, StringComparer.Ordinal))
                {
                    forms.Add(form);
                }
            }
        }

        // Longest first: when one configured secret is a prefix of another, replacing the
        // shorter one first would leave the rest of the longer one in the text.
        string result = text!;
        foreach (string form in forms.OrderByDescending(form => form.Length))
        {
            result = result.Replace(form, Mask);
        }

        return result;
    }

    /// <summary>
    /// The exception as text - message, inner exceptions and stack - with every secret masked.
    /// </summary>
    public static string Redact(Exception? error, IEnumerable<string?>? secrets)
    {
        return error == null ? string.Empty : Redact(error.ToString(), secrets);
    }

    /// <summary>Every encoded spelling of one secret that could appear in error text.</summary>
    private static IEnumerable<string> Variants(string secret)
    {
        yield return secret;

        string percentEncoded = Uri.EscapeDataString(secret);
        yield return percentEncoded;
        yield return LowerPercentHex(percentEncoded);

        yield return JsonEscaped(secret, DefaultEscaping);
        yield return JsonEscaped(secret, RelaxedEscaping);
    }

    /// <summary>The secret as System.Text.Json would write it inside a JSON string, unquoted.</summary>
    private static string JsonEscaped(string secret, JsonSerializerOptions options)
    {
        string quoted = JsonSerializer.Serialize(secret, options);
        return quoted.Substring(1, quoted.Length - 2);
    }

    /// <summary>
    /// The percent-encoded form with lower-case hex digits. Uri.EscapeDataString writes
    /// upper-case; encodeURIComponent-style helpers elsewhere write lower-case, and both
    /// spellings disclose the key.
    /// </summary>
    private static string LowerPercentHex(string encoded)
    {
        var builder = new StringBuilder(encoded.Length);
        for (int index = 0; index < encoded.Length; index++)
        {
            if (encoded[index] == '%' && index + 2 < encoded.Length)
            {
                builder.Append('%');
                builder.Append(char.ToLowerInvariant(encoded[index + 1]));
                builder.Append(char.ToLowerInvariant(encoded[index + 2]));
                index += 2;
            }
            else
            {
                builder.Append(encoded[index]);
            }
        }

        return builder.ToString();
    }
}
