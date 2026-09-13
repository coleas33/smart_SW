using System;
using System.Collections.Generic;
using SwReview.Extractor.Dump;

namespace SwReview.Extractor.Console;

/// <summary>Raised for a bad command line. The host prints the message and exits 1.</summary>
public sealed class UsageError : Exception
{
    public UsageError(string message)
        : base(message)
    {
    }
}

/// <summary>
/// A tiny <c>--name value</c> parser. No library, because contracts/cli.md lists a dozen
/// options across five commands and a parser generator would be more code than the parser.
/// An unknown option is an error rather than a silent no-op: a typo in
/// <c>--meshes none</c> must not quietly write meshes.
/// </summary>
public sealed class CommandLine
{
    private readonly Dictionary<string, string?> _options =
        new Dictionary<string, string?>(StringComparer.OrdinalIgnoreCase);

    private CommandLine()
    {
    }

    /// <summary>Parses <c>--name value</c> pairs and bare <c>--flag</c> switches.</summary>
    public static CommandLine Parse(string[] args, int startIndex, IReadOnlyCollection<string> known)
    {
        var parsed = new CommandLine();

        for (int i = startIndex; i < args.Length; i++)
        {
            string token = args[i];
            if (!token.StartsWith("--", StringComparison.Ordinal))
            {
                throw new UsageError($"Unexpected argument '{token}'; options look like --name value.");
            }

            string name = token.Substring(2);
            if (!Contains(known, name))
            {
                throw new UsageError($"Unknown option '--{name}'.");
            }

            bool hasValue = i + 1 < args.Length && !args[i + 1].StartsWith("--", StringComparison.Ordinal);
            parsed._options[name] = hasValue ? args[++i] : null;
        }

        return parsed;
    }

    /// <summary>The value of an option, or null when it was not given.</summary>
    public string? Value(string name) =>
        _options.TryGetValue(name, out string? value) ? value : null;

    /// <summary>The value of an option that must be present and non-empty.</summary>
    public string Required(string name)
    {
        string? value = Value(name);
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new UsageError($"--{name} is required.");
        }

        return value!;
    }

    /// <summary><c>--meshes glb|stl|none</c>, defaulting to glb.</summary>
    public MeshFormat MeshFormat()
    {
        string value = Value("meshes") ?? "glb";
        switch (value.ToLowerInvariant())
        {
            case "glb":
                return Dump.MeshFormat.Glb;
            case "stl":
                return Dump.MeshFormat.Stl;
            case "none":
                return Dump.MeshFormat.None;
            default:
                throw new UsageError($"--meshes must be glb, stl or none; got '{value}'.");
        }
    }

    /// <summary><c>--faces needed|all</c>, defaulting to needed.</summary>
    public FaceScope FaceScope()
    {
        string value = Value("faces") ?? "needed";
        switch (value.ToLowerInvariant())
        {
            case "needed":
                return Dump.FaceScope.Needed;
            case "all":
                return Dump.FaceScope.All;
            default:
                throw new UsageError($"--faces must be needed or all; got '{value}'.");
        }
    }

    private static bool Contains(IReadOnlyCollection<string> known, string name)
    {
        foreach (string candidate in known)
        {
            if (string.Equals(candidate, name, StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }

        return false;
    }
}
