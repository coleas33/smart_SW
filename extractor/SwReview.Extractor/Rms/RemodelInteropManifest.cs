using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;

namespace SwReview.Extractor.Rms;

/// <summary>
/// The two interop assemblies a manifest is read from, each with the namespace its types live in:
/// <c>SolidWorks.Interop.sldworks</c> for the members and the absences, and
/// <c>SolidWorks.Interop.swconst</c> for the constants. Only their metadata is read - types and
/// methods - and no COM object is ever created from them.
/// </summary>
public sealed class RemodelInteropAssemblies
{
    /// <summary>The members' assembly, as the redist folder names its file.</summary>
    public const string SldWorksName = "SolidWorks.Interop.sldworks";

    /// <summary>The constants' assembly, as the redist folder names its file.</summary>
    public const string SwConstName = "SolidWorks.Interop.swconst";

    public RemodelInteropAssemblies(
        Assembly sldworks, string sldworksNamespace, Assembly swconst, string swconstNamespace)
    {
        SldWorks = sldworks ?? throw new ArgumentNullException(nameof(sldworks));
        SldWorksNamespace = sldworksNamespace ?? throw new ArgumentNullException(nameof(sldworksNamespace));
        SwConst = swconst ?? throw new ArgumentNullException(nameof(swconst));
        SwConstNamespace = swconstNamespace ?? throw new ArgumentNullException(nameof(swconstNamespace));
    }

    public Assembly SldWorks { get; }

    public string SldWorksNamespace { get; }

    public Assembly SwConst { get; }

    public string SwConstNamespace { get; }

    /// <summary>
    /// The installed pair in a seat's <c>api\redist</c> folder, loaded for their metadata. Null when
    /// the folder is blank or does not hold both files, so the caller says which folder it looked in.
    /// </summary>
    public static RemodelInteropAssemblies? FromRedist(string? redistFolder)
    {
        if (string.IsNullOrWhiteSpace(redistFolder))
        {
            return null;
        }

        string sldworks = Path.Combine(redistFolder!, SldWorksName + ".dll");
        string swconst = Path.Combine(redistFolder!, SwConstName + ".dll");
        if (!File.Exists(sldworks) || !File.Exists(swconst))
        {
            return null;
        }

        return new RemodelInteropAssemblies(
            Assembly.LoadFrom(sldworks), SldWorksName, Assembly.LoadFrom(swconst), SwConstName);
    }
}

/// <summary>One parameter of a manifest row, as reflection reads it.</summary>
public sealed class RemodelInteropParameter
{
    public RemodelInteropParameter(string name, string type, bool byRef)
    {
        Name = name;
        Type = type;
        ByRef = byRef;
    }

    public string Name { get; }

    /// <summary>The parameter type's full name; a by-reference parameter's ends in <c>&amp;</c>.</summary>
    public string Type { get; }

    /// <summary>An out-parameter, which is written as <c>"by_ref": true</c> and only then.</summary>
    public bool ByRef { get; }
}

/// <summary>One member row of the manifest: the selection's fields beside reflection's.</summary>
public sealed class RemodelInteropManifestRow
{
    public RemodelInteropManifestRow(
        RemodelInteropCall selected, string kind, IReadOnlyList<RemodelInteropParameter> parameters, string returns)
    {
        Selected = selected ?? throw new ArgumentNullException(nameof(selected));
        Kind = kind;
        Parameters = parameters;
        Returns = returns;
    }

    /// <summary>The builder table's call this row records: its key, <c>used_by</c>, <c>allowlisted</c> and <c>note</c>.</summary>
    public RemodelInteropCall Selected { get; }

    public string Interface => Selected.Interface;

    public string Member => Selected.Member;

    public string Key => Selected.Key;

    /// <summary><c>method</c>, <c>property-get</c> or <c>property-set</c>, as reflection reads it.</summary>
    public string Kind { get; }

    public IReadOnlyList<RemodelInteropParameter> Parameters { get; }

    public string Returns { get; }

    /// <summary>The one spelling of this row's signature, <see cref="RemodelInteropManifest.Signature"/>'s.</summary>
    public string Signature =>
        RemodelInteropManifest.Signature(Parameters.Select(p => new KeyValuePair<string, string>(p.Name, p.Type)), Returns);
}

/// <summary>One enum of the manifest's block: its name and each recorded constant's integer, in order.</summary>
public sealed class RemodelInteropEnumRow
{
    public RemodelInteropEnumRow(string name, IReadOnlyList<KeyValuePair<string, int>> values)
    {
        Name = name;
        Values = values;
    }

    public string Name { get; }

    public IReadOnlyList<KeyValuePair<string, int>> Values { get; }
}

/// <summary>A whole manifest, as <see cref="RemodelInteropManifest.Write"/> writes it.</summary>
public sealed class RemodelInteropManifestDocument
{
    public RemodelInteropManifestDocument(
        string assembly,
        string assemblyVersion,
        string swconstVersion,
        string product,
        DateTime generatedAt,
        IReadOnlyList<RemodelInteropManifestRow> members,
        IReadOnlyList<RemodelInteropEnumRow> enums,
        IReadOnlyList<RemodelInteropAbsence> absences)
    {
        Assembly = assembly;
        AssemblyVersion = assemblyVersion;
        SwconstVersion = swconstVersion;
        Product = product;
        GeneratedAt = generatedAt;
        Members = members;
        Enums = enums;
        Absences = absences;
    }

    public string Schema => RemodelInteropManifest.SchemaVersion;

    public string Assembly { get; }

    public string AssemblyVersion { get; }

    public string SwconstVersion { get; }

    public string Product { get; }

    /// <summary>When the command ran, in UTC, to the second.</summary>
    public DateTime GeneratedAt { get; }

    public string GeneratedBy => RemodelInteropManifest.GeneratedBy;

    public IReadOnlyList<RemodelInteropManifestRow> Members { get; }

    public IReadOnlyList<RemodelInteropEnumRow> Enums { get; }

    public IReadOnlyList<RemodelInteropAbsence> Absences { get; }
}

/// <summary>
/// What a generation produced: the document, holding every row and constant reflection could
/// read, and one sentence per thing it could not. A generation with any problem is never written
/// (<c>swreview-extract probe interop</c> exits 1); test B reads both halves.
/// </summary>
public sealed class RemodelInteropGeneration
{
    public RemodelInteropGeneration(RemodelInteropManifestDocument document, IReadOnlyList<string> problems)
    {
        Document = document;
        Problems = problems;
    }

    public RemodelInteropManifestDocument Document { get; }

    public IReadOnlyList<string> Problems { get; }

    public bool Succeeded => Problems.Count == 0;
}

/// <summary>
/// 004 T181 (default taken 2026-09-27, the owner may revise; research R15.1): the frozen
/// interop-surface manifest, regenerated rather than typed. The <b>selection</b> - which rows in
/// which order with their <c>used_by</c>, <c>allowlisted</c> and <c>note</c>, which swconst
/// constants, which absences - is committed code, <see cref="RemodelInteropSurface"/>; every other
/// field is read here, by reflection over the installed interop assemblies' metadata:
///
///   - a row's <c>kind</c> (a <c>get_</c> or <c>set_</c> special name is a property's accessor,
///     anything else a method), <c>arity</c>, ordered <c>parameters</c> with <c>by_ref</c>, and
///     <c>returns</c>;
///   - each constant's integer;
///   - the two assembly versions, and <c>product</c> from the members' version (<see cref="ProductFor"/>).
///
/// A problem - an interface or member missing, a member with more than one overload, an absence
/// that is present, an enum or constant missing, a row with no <c>used_by</c> - is a sentence in
/// <see cref="RemodelInteropGeneration.Problems"/>, and the manifest is not written.
///
/// <b>Nothing here creates a COM object or touches SOLIDWORKS</b>: types and methods are read, and
/// nothing is invoked. <see cref="Write"/> writes the fixture's existing format - two-space
/// indentation, its key order, <c>by_ref</c> only when true, a note only when there is one, LF line
/// ends and a final newline - so a regeneration's diff is only what moved.
/// </summary>
public static class RemodelInteropManifest
{
    /// <summary>The manifest's <c>manifest_schema</c>.</summary>
    public const string SchemaVersion = "1.0";

    /// <summary>The manifest's <c>generated_by</c>: the one command that writes it.</summary>
    public const string GeneratedBy = "swreview-extract probe interop --emit-manifest";

    /// <summary>The spelling of <c>generated_at</c>: UTC, to the second.</summary>
    public const string GeneratedAtFormat = "yyyy-MM-dd'T'HH:mm:ss'Z'";

    private const string Method = "method";
    private const string PropertyGet = "property-get";
    private const string PropertySet = "property-set";

    /// <summary>
    /// The committed selection (<see cref="RemodelInteropSurface"/>) read against
    /// <paramref name="interop"/>.
    /// </summary>
    public static RemodelInteropGeneration Generate(RemodelInteropAssemblies interop, DateTime generatedAtUtc) =>
        Generate(
            RemodelInteropSurface.Calls,
            RemodelInteropSurface.Constants,
            RemodelInteropSurface.Absences,
            interop,
            generatedAtUtc);

    /// <summary>A selection read against <paramref name="interop"/>: every row, constant and absence, and every problem.</summary>
    public static RemodelInteropGeneration Generate(
        IReadOnlyList<RemodelInteropCall> calls,
        IReadOnlyList<RemodelInteropConstants> constants,
        IReadOnlyList<RemodelInteropAbsence> absences,
        RemodelInteropAssemblies interop,
        DateTime generatedAtUtc)
    {
        if (calls == null)
        {
            throw new ArgumentNullException(nameof(calls));
        }

        if (constants == null)
        {
            throw new ArgumentNullException(nameof(constants));
        }

        if (absences == null)
        {
            throw new ArgumentNullException(nameof(absences));
        }

        if (interop == null)
        {
            throw new ArgumentNullException(nameof(interop));
        }

        var problems = new List<string>();
        var rows = new List<RemodelInteropManifestRow>();
        foreach (IGrouping<string, RemodelInteropCall> duplicate in calls
                     .GroupBy(call => call.Key, StringComparer.Ordinal)
                     .Where(group => group.Count() > 1))
        {
            problems.Add($"{duplicate.Key} is selected {duplicate.Count()} times; a manifest has one row per member");
        }

        foreach (RemodelInteropCall call in calls)
        {
            RemodelInteropManifestRow? row = ReadRow(call, interop, problems);
            if (row != null)
            {
                rows.Add(row);
            }
        }

        var enums = new List<RemodelInteropEnumRow>();
        foreach (RemodelInteropConstants selected in constants)
        {
            RemodelInteropEnumRow? row = ReadEnum(selected, interop, problems);
            if (row != null)
            {
                enums.Add(row);
            }
        }

        foreach (RemodelInteropAbsence absence in absences)
        {
            CheckAbsence(absence, interop, problems);
        }

        var document = new RemodelInteropManifestDocument(
            interop.SldWorks.GetName().Name,
            VersionOf(interop.SldWorks),
            VersionOf(interop.SwConst),
            ProductFor(interop.SldWorks.GetName().Version),
            Truncate(generatedAtUtc),
            rows,
            enums,
            absences);
        return new RemodelInteropGeneration(document, problems);
    }

    /// <summary>
    /// The product an interop version belongs to: <c>SOLIDWORKS {1992 + major} SP{minor}</c>, so
    /// 32.5 is SOLIDWORKS 2024 SP5 (default taken 2026-09-27, the owner may revise; the interop
    /// assemblies carry no product name). Null reads as unknown.
    /// </summary>
    public static string ProductFor(Version? version) =>
        version == null
            ? "SOLIDWORKS (unknown version)"
            : string.Format(CultureInfo.InvariantCulture, "SOLIDWORKS {0} SP{1}", 1992 + version.Major, version.Minor);

    /// <summary>
    /// The one spelling of a signature every comparison of the manifest uses:
    /// <c>(name:type, name:type) -&gt; returns</c>, parameters in order.
    /// </summary>
    public static string Signature(IEnumerable<KeyValuePair<string, string>> parameters, string returns) =>
        "(" + string.Join(", ", parameters.Select(p => p.Key + ":" + p.Value)) + ") -> " + returns;

    /// <summary>The manifest as the fixture holds it: UTF-8 text with LF line ends and a final newline.</summary>
    public static string Write(RemodelInteropManifestDocument document)
    {
        if (document == null)
        {
            throw new ArgumentNullException(nameof(document));
        }

        var options = new JsonWriterOptions
        {
            Indented = true,
            Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        };

        using (var stream = new MemoryStream())
        {
            using (var json = new Utf8JsonWriter(stream, options))
            {
                json.WriteStartObject();
                json.WriteString("manifest_schema", document.Schema);
                json.WriteString("assembly", document.Assembly);
                json.WriteString("assembly_version", document.AssemblyVersion);
                json.WriteString("swconst_version", document.SwconstVersion);
                json.WriteString("product", document.Product);
                json.WriteString(
                    "generated_at", document.GeneratedAt.ToString(GeneratedAtFormat, CultureInfo.InvariantCulture));
                json.WriteString("generated_by", document.GeneratedBy);

                json.WriteStartArray("members");
                foreach (RemodelInteropManifestRow row in document.Members)
                {
                    WriteRow(json, row);
                }

                json.WriteEndArray();

                json.WriteStartArray("enums");
                foreach (RemodelInteropEnumRow row in document.Enums)
                {
                    json.WriteStartObject();
                    json.WriteString("enum", row.Name);
                    json.WriteStartObject("values");
                    foreach (KeyValuePair<string, int> value in row.Values)
                    {
                        json.WriteNumber(value.Key, value.Value);
                    }

                    json.WriteEndObject();
                    json.WriteEndObject();
                }

                json.WriteEndArray();

                json.WriteStartArray("absences");
                foreach (RemodelInteropAbsence absence in document.Absences)
                {
                    WriteAbsence(json, absence);
                }

                json.WriteEndArray();
                json.WriteEndObject();
            }

            string text = Encoding.UTF8.GetString(stream.ToArray());
            return text.Replace("\r\n", "\n") + "\n";
        }
    }

    private static void WriteRow(Utf8JsonWriter json, RemodelInteropManifestRow row)
    {
        json.WriteStartObject();
        json.WriteString("interface", row.Interface);
        json.WriteString("member", row.Member);
        json.WriteString("kind", row.Kind);
        json.WriteNumber("arity", row.Parameters.Count);
        json.WriteStartArray("parameters");
        foreach (RemodelInteropParameter parameter in row.Parameters)
        {
            json.WriteStartObject();
            json.WriteString("name", parameter.Name);
            json.WriteString("type", parameter.Type);
            if (parameter.ByRef)
            {
                json.WriteBoolean("by_ref", true);
            }

            json.WriteEndObject();
        }

        json.WriteEndArray();
        json.WriteString("returns", row.Returns);
        json.WriteStartArray("used_by");
        foreach (string command in row.Selected.UsedBy)
        {
            json.WriteStringValue(command);
        }

        json.WriteEndArray();
        json.WriteBoolean("allowlisted", row.Selected.Allowlisted);
        if (row.Selected.Note != null)
        {
            json.WriteString("note", row.Selected.Note);
        }

        json.WriteEndObject();
    }

    private static void WriteAbsence(Utf8JsonWriter json, RemodelInteropAbsence absence)
    {
        json.WriteStartObject();
        json.WriteString("interface", absence.Interface);
        if (absence.Member != null)
        {
            json.WriteString("member", absence.Member);
        }
        else
        {
            json.WriteString("member_pattern", absence.MemberPattern);
        }

        if (absence.Except.Count > 0)
        {
            json.WriteStartArray("except");
            foreach (string name in absence.Except)
            {
                json.WriteStringValue(name);
            }

            json.WriteEndArray();
        }

        json.WriteString("consequence", absence.Consequence);
        json.WriteEndObject();
    }

    private static RemodelInteropManifestRow? ReadRow(
        RemodelInteropCall call, RemodelInteropAssemblies interop, List<string> problems)
    {
        if (call.UsedBy.Count == 0 || call.UsedBy.Any(string.IsNullOrWhiteSpace))
        {
            problems.Add($"{call.Key} names no command in used_by; every row says who calls it");
            return null;
        }

        Type? type = interop.SldWorks.GetType(interop.SldWorksNamespace + "." + call.Interface);
        if (type == null)
        {
            problems.Add($"{call.Interface} is gone from the installed {interop.SldWorks.GetName().Name} ({call.Key})");
            return null;
        }

        MethodInfo[] found = type.GetMethods()
            .Where(method => string.Equals(method.Name, call.Member, StringComparison.Ordinal))
            .ToArray();
        if (found.Length == 0)
        {
            problems.Add($"{call.Key} is gone from the installed {interop.SldWorks.GetName().Name}");
            return null;
        }

        if (found.Length > 1)
        {
            problems.Add(
                $"{call.Key} has {found.Length} overloads on the installed assembly, so one row's "
                + "signature no longer identifies it");
            return null;
        }

        MethodInfo method = found[0];
        RemodelInteropParameter[] parameters = method.GetParameters()
            .Select(parameter => new RemodelInteropParameter(
                parameter.Name, parameter.ParameterType.FullName, parameter.ParameterType.IsByRef))
            .ToArray();
        return new RemodelInteropManifestRow(call, KindOf(method), parameters, method.ReturnType.FullName);
    }

    private static RemodelInteropEnumRow? ReadEnum(
        RemodelInteropConstants selected, RemodelInteropAssemblies interop, List<string> problems)
    {
        Type? type = interop.SwConst.GetType(interop.SwConstNamespace + "." + selected.Enum);
        if (type == null || !type.IsEnum)
        {
            problems.Add($"{selected.Enum} is gone from the installed {interop.SwConst.GetName().Name}");
            return null;
        }

        var values = new List<KeyValuePair<string, int>>();
        foreach (string member in selected.Members)
        {
            if (!Enum.IsDefined(type, member))
            {
                problems.Add($"{selected.Enum}.{member} is gone from the installed {interop.SwConst.GetName().Name}");
                continue;
            }

            values.Add(new KeyValuePair<string, int>(
                member, Convert.ToInt32(Enum.Parse(type, member), CultureInfo.InvariantCulture)));
        }

        return new RemodelInteropEnumRow(selected.Enum, values);
    }

    private static void CheckAbsence(RemodelInteropAbsence absence, RemodelInteropAssemblies interop, List<string> problems)
    {
        Type? type = interop.SldWorks.GetType(interop.SldWorksNamespace + "." + absence.Interface);
        if (type == null)
        {
            problems.Add($"{absence.Interface} is gone, so its recorded absence cannot be checked");
            return;
        }

        string[] appeared = type.GetMembers()
            .Select(member => member.Name)
            .Distinct(StringComparer.Ordinal)
            .Where(absence.Matches)
            .OrderBy(name => name, StringComparer.Ordinal)
            .ToArray();
        if (appeared.Length > 0)
        {
            problems.Add(
                $"{absence.Interface}.{absence.Member ?? absence.MemberPattern} was absent and is now present as "
                + $"{string.Join(", ", appeared)}; the design depends on its absence: {absence.Consequence}");
        }
    }

    private static string KindOf(MethodInfo method)
    {
        if (method.IsSpecialName && method.Name.StartsWith("get_", StringComparison.Ordinal))
        {
            return PropertyGet;
        }

        if (method.IsSpecialName && method.Name.StartsWith("set_", StringComparison.Ordinal))
        {
            return PropertySet;
        }

        return Method;
    }

    private static string VersionOf(Assembly assembly) =>
        assembly.GetName().Version?.ToString() ?? "(none)";

    private static DateTime Truncate(DateTime at)
    {
        DateTime utc = at.Kind == DateTimeKind.Local ? at.ToUniversalTime() : at;
        return new DateTime(utc.Ticks - (utc.Ticks % TimeSpan.TicksPerSecond), DateTimeKind.Utc);
    }
}
