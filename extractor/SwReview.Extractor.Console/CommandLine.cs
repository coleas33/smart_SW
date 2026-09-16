using System;
using System.Collections.Generic;
using System.Globalization;
using SwReview.Extractor.Capture;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Interference;
using SwReview.Extractor.Ir;

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

    private readonly Dictionary<string, List<string>> _lists =
        new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);

    private CommandLine()
    {
    }

    /// <summary>
    /// Parses <c>--name value</c> pairs and bare <c>--flag</c> switches. An option may carry
    /// several values (<c>--pairs a,b c,d</c>): <see cref="Value"/> returns the first and
    /// <see cref="Values"/> returns all of them, so single-valued options are unaffected.
    /// </summary>
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

            var values = new List<string>();
            while (i + 1 < args.Length && !args[i + 1].StartsWith("--", StringComparison.Ordinal))
            {
                values.Add(args[++i]);
            }

            parsed._options[name] = values.Count == 0 ? null : values[0];
            parsed._lists[name] = values;
        }

        return parsed;
    }

    /// <summary>True when the option appeared at all, with or without a value.</summary>
    public bool Has(string name) => _options.ContainsKey(name);

    /// <summary>The first value of an option, or null when it was not given.</summary>
    public string? Value(string name) =>
        _options.TryGetValue(name, out string? value) ? value : null;

    /// <summary>Every value of an option, in order; empty when it was not given.</summary>
    public IReadOnlyList<string> Values(string name) =>
        _lists.TryGetValue(name, out List<string> values) ? values : (IReadOnlyList<string>)new string[0];

    /// <summary>
    /// A boolean switch: <c>--flag</c>, or <c>--flag true|false</c>. Absent means false, so a
    /// run that did not ask for coincidence detection does not get it.
    /// </summary>
    public bool Flag(string name)
    {
        if (!_options.TryGetValue(name, out string? value))
        {
            return false;
        }

        if (value == null)
        {
            return true;
        }

        switch (value.Trim().ToLowerInvariant())
        {
            case "true":
            case "yes":
            case "1":
                return true;
            case "false":
            case "no":
            case "0":
                return false;
            default:
                throw new UsageError($"--{name} takes no value, or true|false; got '{value}'.");
        }
    }

    /// <summary>A whole-number option, or null when it was not given.</summary>
    public int? Int(string name)
    {
        string? value = Value(name);
        if (string.IsNullOrWhiteSpace(value))
        {
            if (_options.ContainsKey(name))
            {
                throw new UsageError($"--{name} needs a whole number.");
            }

            return null;
        }

        int parsed;
        if (!int.TryParse(value, NumberStyles.None, CultureInfo.InvariantCulture, out parsed))
        {
            throw new UsageError($"--{name} must be a whole number; got '{value}'.");
        }

        return parsed;
    }

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

    /// <summary><c>--features tree|none</c>, defaulting to tree (contracts/cli.md).</summary>
    public FeatureScope FeatureScope()
    {
        string value = Value("features") ?? "tree";
        switch (value.ToLowerInvariant())
        {
            case "tree":
                return Dump.FeatureScope.Tree;
            case "none":
                return Dump.FeatureScope.None;
            default:
                throw new UsageError($"--features must be tree or none; got '{value}'.");
        }
    }

    /// <summary><c>--equations on|off</c>, defaulting to on (contracts/cli.md).</summary>
    public EquationScope EquationScope()
    {
        string value = Value("equations") ?? "on";
        switch (value.ToLowerInvariant())
        {
            case "on":
                return Dump.EquationScope.On;
            case "off":
                return Dump.EquationScope.Off;
            default:
                throw new UsageError($"--equations must be on or off; got '{value}'.");
        }
    }

    /// <summary>
    /// <c>--fasteners include|exclude|only</c>, defaulting to include (contracts/cli.md).
    /// </summary>
    public FastenerFolderTreatment FastenerTreatment()
    {
        try
        {
            return InterferenceRunSettings.ParseFastenerTreatment(Value("fasteners"));
        }
        catch (ArgumentException error)
        {
            throw new UsageError(error.Message);
        }
    }

    /// <summary><c>--view iso|front|top|right|fit</c>, defaulting to fit.</summary>
    public string CaptureView()
    {
        string? value = Value("view");
        if (!CaptureViews.IsKnown(value ?? CaptureViews.Fit))
        {
            throw new UsageError(
                $"--view must be {string.Join(", ", CaptureViews.All)}; got '{value}'.");
        }

        return CaptureViews.Normalize(value);
    }

    /// <summary>
    /// <c>--pairs all|&lt;id,id&gt;...</c>. Each value after the first form is one pair of
    /// component ids separated by a comma: <c>--pairs cmp:0001,cmp:0011 cmp:0001,cmp:0012</c>.
    /// An empty list means the caller did not say, which the host treats as <c>all</c>.
    /// </summary>
    public IReadOnlyList<string[]> Pairs()
    {
        IReadOnlyList<string> values = Values("pairs");
        var pairs = new List<string[]>();

        foreach (string value in values)
        {
            if (string.Equals(value, "all", StringComparison.OrdinalIgnoreCase))
            {
                if (values.Count > 1)
                {
                    throw new UsageError("--pairs all cannot be combined with named pairs.");
                }

                return pairs;
            }

            string[] ids = value.Split(',');
            if (ids.Length != 2 || string.IsNullOrWhiteSpace(ids[0]) || string.IsNullOrWhiteSpace(ids[1]))
            {
                throw new UsageError(
                    $"--pairs takes 'all' or pairs of component ids like cmp:0001,cmp:0011; got '{value}'.");
            }

            pairs.Add(new[] { ids[0].Trim(), ids[1].Trim() });
        }

        return pairs;
    }

    /// <summary>True when <c>--pairs</c> was given as anything other than <c>all</c>.</summary>
    public bool HasNamedPairs() => Pairs().Count > 0;

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
