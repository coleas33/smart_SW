using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;

namespace SwReview.AddIn.Tests;

/// <summary>
/// `reviewer/src/swreview/chat/server.py`, read as text, for the tests that tie the add-in's
/// copies of the backend's rules to the backend's own source rather than to a second
/// hand-written list (owner decision 143A): the status and `retryable` flag each error class is
/// answered with, and the routes whose handler starts a turn. The add-in cannot run Python, so
/// the source is read, as the wiring tests read the add-in's.
/// </summary>
internal static class ChatServerSource
{
    private static readonly Lazy<string[]> Lines = new Lazy<string[]>(() => File.ReadAllLines(Path.Combine(
        ErrorLabelsCoverTheHostTests.RepositoryRoot(), "reviewer", "src", "swreview", "chat", "server.py")));

    /// <summary>
    /// The HTTP status and `retryable` flag the backend answers <paramref name="errorClass"/>
    /// with: the `ChatError` subclass whose `error_class` it is, with what it does not set taken
    /// from the class it derives from, down to `ChatError` itself.
    /// </summary>
    public static (int Status, bool Retryable) ErrorClass(string errorClass)
    {
        Dictionary<string, PythonClass> classes = Classes();
        PythonClass[] named = classes
            .Where(candidate => IsChatError(classes, candidate.Key)
                && Resolve(classes, candidate.Value, body => body.ErrorClass) == errorClass)
            .Select(candidate => candidate.Value)
            .ToArray();
        if (named.Length != 1)
        {
            throw new InvalidOperationException(
                $"chat/server.py has {named.Length} classes answering '{errorClass}', not one");
        }

        return (
            int.Parse(Resolve(classes, named[0], body => body.Status) ?? "400", System.Globalization.CultureInfo.InvariantCulture),
            (Resolve(classes, named[0], body => body.Retryable) ?? "False") == "True");
    }

    /// <summary>
    /// Every route the backend serves, by method and path, with whether its handler moves a chat
    /// to `RUNNING` - starts a turn, or resumes one.
    /// </summary>
    public static IReadOnlyList<(string Method, string Path, bool StartsATurn)> Routes()
    {
        string text = string.Join("\n", Lines.Value);
        var routes = new List<(string, string, bool)>();
        foreach (Match route in Regex.Matches(
            text, @"Route\(\s*""(?<path>[^""]+)"",\s*server\.(?<handler>\w+),\s*methods=\[(?<methods>[^\]]+)\]"))
        {
            bool turn = HandlerBody(route.Groups["handler"].Value).Contains(".to(ChatState.RUNNING)");
            foreach (Match method in Regex.Matches(route.Groups["methods"].Value, @"""(\w+)"""))
            {
                routes.Add((method.Groups[1].Value, route.Groups["path"].Value, turn));
            }
        }

        if (routes.Count == 0)
        {
            throw new InvalidOperationException("chat/server.py no longer lists its routes as Route(...) rows");
        }

        return routes;
    }

    /// <summary>The body of the server's method <paramref name="name"/>, up to the next method.</summary>
    private static string HandlerBody(string name)
    {
        string[] lines = Lines.Value;
        int start = Array.FindIndex(lines, line => Regex.IsMatch(line, @"^    (async )?def " + Regex.Escape(name) + @"\("));
        if (start < 0)
        {
            throw new InvalidOperationException($"chat/server.py has no method '{name}'");
        }

        var body = new List<string>();
        for (int index = start + 1; index < lines.Length; index++)
        {
            string line = lines[index];
            if (Regex.IsMatch(line, @"^    (async )?def ") || Regex.IsMatch(line, @"^\S"))
            {
                break;
            }

            body.Add(line);
        }

        return string.Join("\n", body);
    }

    private static Dictionary<string, PythonClass> Classes()
    {
        var classes = new Dictionary<string, PythonClass>(StringComparer.Ordinal);
        string[] lines = Lines.Value;
        for (int index = 0; index < lines.Length; index++)
        {
            Match head = Regex.Match(lines[index], @"^class (\w+)\((\w+)\):");
            if (!head.Success)
            {
                continue;
            }

            var found = new PythonClass(head.Groups[2].Value);
            for (int inner = index + 1; inner < lines.Length && !Regex.IsMatch(lines[inner], @"^\S"); inner++)
            {
                Match field = Regex.Match(lines[inner], @"^    (status|error_class|retryable)\s*(?::[^=]+)?=\s*(.+?)\s*$");
                if (!field.Success)
                {
                    continue;
                }

                string value = field.Groups[2].Value.Trim('"');
                switch (field.Groups[1].Value)
                {
                    case "status":
                        found.Status = value;
                        break;

                    case "error_class":
                        found.ErrorClass = value;
                        break;

                    default:
                        found.Retryable = value;
                        break;
                }
            }

            classes[head.Groups[1].Value] = found;
        }

        if (!classes.ContainsKey("ChatError"))
        {
            throw new InvalidOperationException("chat/server.py no longer defines ChatError");
        }

        return classes;
    }

    /// <summary>Whether the class <paramref name="name"/> is `ChatError` or derives from it.</summary>
    private static bool IsChatError(Dictionary<string, PythonClass> classes, string name)
    {
        for (string? current = name; current != null;)
        {
            if (current == "ChatError")
            {
                return true;
            }

            current = classes.TryGetValue(current, out PythonClass? found) ? found.Base : null;
        }

        return false;
    }

    /// <summary>A field of <paramref name="start"/>, or of the nearest class it derives from that sets it.</summary>
    private static string? Resolve(
        Dictionary<string, PythonClass> classes, PythonClass start, Func<PythonClass, string?> field)
    {
        for (PythonClass? current = start; current != null;)
        {
            string? value = field(current);
            if (value != null)
            {
                return value;
            }

            current = classes.TryGetValue(current.Base, out PythonClass? parent) ? parent : null;
        }

        return null;
    }

    private sealed class PythonClass
    {
        public PythonClass(string baseName)
        {
            Base = baseName;
        }

        public string Base { get; }

        public string? Status { get; set; }

        public string? ErrorClass { get; set; }

        public string? Retryable { get; set; }
    }
}
