using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.Json;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Rms;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T054 and T056. The frozen interop-surface manifest
/// (<c>Fixtures/InteropSurface/remodel-interop-manifest.json</c>, the one path
/// contracts/interop-manifest.md and plan.md both name) and its two tests.
///
/// Every member on the stage-1 allowlist is VERIFIED: it exists with that signature on
/// SOLIDWORKS 2024 SP5 interop <c>32.5.0.48</c>. Nothing keeps that true. An upgrade can change
/// an arity, reorder parameters, turn a ByRef out-parameter into a return value, or remove a
/// member, and the failure mode is a <c>COMException</c> or, worse, a silently wrong argument at
/// the one moment the code is writing to a document.
///
/// The manifest also records the <b>absences</b> the design depends on, which is the half a
/// signature dump normally loses: <c>IEquationMgr.set_GlobalVariable</c> is absent, so a global
/// is created by equation syntax; <c>ISketchRelation.Name</c> is absent, so sketch relations
/// cannot be named; <c>IFeature.set_ShowFeatureDescription</c> is absent, so a hidden
/// description can be detected and not turned on. A design that assumed any of those would look
/// reasonable and be wrong.
///
///   - <see cref="CodeMatchesManifest"/> is pure and always runs: the argument-builder table in
///     <see cref="RemodelInteropSurface"/> against the fixture.
///   - <see cref="InstalledAssemblyMatchesManifest"/> regenerates the surface from the
///     <b>installed</b> assembly and diffs it, and is skipped - with its reason - when the
///     interop DLL is absent, so CI stays green on a machine with no SOLIDWORKS. It is what
///     turns a SOLIDWORKS upgrade from a runtime surprise into a red build.
///
/// Regenerating the fixture is a deliberate, reviewed commit. Neither test ever updates it.
/// </summary>
public class RemodelInteropManifestTests
{
    /// <summary>The fixture, relative to the test assembly, exactly as the contract names it.</summary>
    private const string FixturePath = @"Fixtures\InteropSurface\remodel-interop-manifest.json";

    private static readonly Manifest Loaded = Manifest.Load();

    // =====================================================================================
    // Test A: pure, runs everywhere, no SOLIDWORKS.
    // =====================================================================================

    /// <summary>
    /// The four rules of contracts/interop-manifest.md, section "Test A":
    ///
    ///   1. every member a builder calls has a manifest row, and every row with
    ///      <c>allowlisted: true</c> has a builder;
    ///   2. the arity and the ordered parameter names the builder uses equal the row's;
    ///   3. the option integers the builders compose equal the manifest's enum values - the
    ///      same integers guard-allowlist.md pins, asserted from one source rather than two;
    ///   4. <c>allowlisted</c> agrees with <see cref="RemodelGuard"/>'s list, as a set equality
    ///      in both directions.
    ///
    /// This fails when someone adds a call without recording it, changes an argument order, or
    /// writes an option as a name whose value drifted.
    /// </summary>
    [Fact]
    public void CodeMatchesManifest()
    {
        EveryBuilderHasARow();
        EveryBuilderMatchesItsRowsSignature();
        EveryComposedOptionEqualsTheManifestsEnumValue();
        AllowlistedRowsAreExactlyTheStage1Allowlist();
    }

    /// <summary>Rule 1, both directions.</summary>
    private static void EveryBuilderHasARow()
    {
        var rows = new HashSet<string>(Loaded.Members.Select(m => m.Key), StringComparer.Ordinal);
        var builders = new HashSet<string>(
            RemodelInteropSurface.Calls.Select(c => c.Key), StringComparer.Ordinal);

        string[] undeclared = builders.Except(rows, StringComparer.Ordinal).OrderBy(k => k, StringComparer.Ordinal).ToArray();
        Assert.True(
            undeclared.Length == 0,
            "the re-modeler calls interop members the frozen manifest does not record, so nothing "
            + "would notice if their signatures moved: " + string.Join(", ", undeclared));

        string[] unreachable = Loaded.Members
            .Where(m => m.Allowlisted)
            .Select(m => m.Key)
            .Except(builders, StringComparer.Ordinal)
            .OrderBy(k => k, StringComparer.Ordinal)
            .ToArray();
        Assert.True(
            unreachable.Length == 0,
            "the manifest marks members allowlisted that no argument builder reaches; an "
            + "allowlist entry without a call path is the accidental widening the allowlist "
            + "exists to prevent: " + string.Join(", ", unreachable));
    }

    /// <summary>
    /// Rule 2. The parameter order is load-bearing: a reordered signature is exactly the failure
    /// a name-only check misses, and the one that writes a wrong argument to a document.
    /// </summary>
    private static void EveryBuilderMatchesItsRowsSignature()
    {
        foreach (RemodelInteropCall call in RemodelInteropSurface.Calls)
        {
            ManifestMember row = Loaded.Member(call.Key);

            Assert.Equal(row.Arity, call.ParameterNames.Count);
            Assert.Equal(row.Parameters.Select(p => p.Name).ToArray(), call.ParameterNames.ToArray());
            Assert.Equal(row.Returns, call.Returns);
            Assert.Equal(row.Kind, call.Kind);
        }
    }

    /// <summary>
    /// Rule 3. Each option is asserted as the integer the code composes against the integers the
    /// manifest records for the enum members it is composed from, so the value and the name it
    /// was written as cannot drift apart silently.
    /// </summary>
    private static void EveryComposedOptionEqualsTheManifestsEnumValue()
    {
        // Read into locals so the assertion compares two values rather than a value with a
        // compile-time constant; the code's constants are what is under test, not the literal.
        int openOptions = RemodelCopy.OpenOptions;
        int saveOptions = RemodelCopy.SaveOptions;
        int tagType = RemodelCopy.SessionTagType;
        int tagOverwrite = RemodelCopy.SessionTagOverwrite;
        int inputDimValOnCreate = RemodelSystemToggles.InputDimValOnCreate;
        int showErrorsEveryRebuild = RemodelSystemToggles.ShowErrorsEveryRebuild;
        int warnSaveUpdateErrors = RemodelSystemToggles.WarnSaveUpdateErrors;

        int silent = Loaded.Enum("swOpenDocOptions_e", "swOpenDocOptions_Silent");
        int loadModel = Loaded.Enum("swOpenDocOptions_e", "swOpenDocOptions_LoadModel");
        int readOnly = Loaded.Enum("swOpenDocOptions_e", "swOpenDocOptions_ReadOnly");
        int viewOnly = Loaded.Enum("swOpenDocOptions_e", "swOpenDocOptions_ViewOnly");

        Assert.Equal(silent | loadModel, openOptions);
        Assert.Equal(0, openOptions & readOnly);
        Assert.Equal(0, openOptions & viewOnly);

        int saveSilent = Loaded.Enum("swSaveAsOptions_e", "swSaveAsOptions_Silent");
        int saveCopy = Loaded.Enum("swSaveAsOptions_e", "swSaveAsOptions_Copy");
        int saveReferenced = Loaded.Enum("swSaveAsOptions_e", "swSaveAsOptions_SaveReferenced");
        int avoidRebuild = Loaded.Enum("swSaveAsOptions_e", "swSaveAsOptions_AvoidRebuildOnSave");

        Assert.Equal(saveSilent, saveOptions);
        Assert.Equal(0, saveOptions & saveCopy);
        Assert.Equal(0, saveOptions & saveReferenced);
        Assert.Equal(0, saveOptions & avoidRebuild);

        Assert.Equal(Loaded.Enum("swCustomInfoType_e", "swCustomInfoText"), tagType);
        Assert.Equal(
            Loaded.Enum("swCustomPropertyAddOption_e", "swCustomPropertyReplaceValue"),
            tagOverwrite);

        Assert.Equal(
            Loaded.Enum("swUserPreferenceToggle_e", "swInputDimValOnCreate"), inputDimValOnCreate);
        Assert.Equal(
            Loaded.Enum("swUserPreferenceToggle_e", "swShowErrorsEveryRebuild"),
            showErrorsEveryRebuild);
        Assert.Equal(
            Loaded.Enum("swUserPreferenceToggle_e", "swWarnSaveUpdateErrors"),
            warnSaveUpdateErrors);
    }

    /// <summary>
    /// Rule 4. A set equality in both directions: a member allowlisted in the guard but not
    /// recorded here has no frozen signature, and a row marked allowlisted that the guard does
    /// not permit is a surface nobody reviewed.
    /// </summary>
    private static void AllowlistedRowsAreExactlyTheStage1Allowlist()
    {
        var manifest = new SortedSet<string>(
            Loaded.Members.Where(m => m.Allowlisted).Select(m => m.Key), StringComparer.Ordinal);
        var guard = new SortedSet<string>(RemodelGuard.AllowedKeys, StringComparer.Ordinal);

        Assert.Equal(guard, manifest);
    }

    // --------------------------------------------------- the fixture's own consistency

    [Fact]
    public void TheManifestNamesTheAssemblyAndTheProductItWasReadFrom()
    {
        Assert.Equal("1.0", Loaded.Schema);
        Assert.Equal("SolidWorks.Interop.sldworks", Loaded.Assembly);
        Assert.Equal("32.5.0.48", Loaded.AssemblyVersion);
        Assert.Equal("32.5.0.48", Loaded.SwconstVersion);
        Assert.Equal("SOLIDWORKS 2024 SP5", Loaded.Product);
    }

    /// <summary>
    /// One row per member: a duplicate would let one spelling of a signature shadow another and
    /// make the set equalities above meaningless.
    /// </summary>
    [Fact]
    public void EveryManifestRowIsUniqueAndWellFormed()
    {
        Assert.Equal(
            Loaded.Members.Count,
            Loaded.Members.Select(m => m.Key).Distinct(StringComparer.Ordinal).Count());

        foreach (ManifestMember member in Loaded.Members)
        {
            Assert.False(string.IsNullOrWhiteSpace(member.Interface), member.Key);
            Assert.False(string.IsNullOrWhiteSpace(member.Member), member.Key);
            Assert.False(string.IsNullOrWhiteSpace(member.Returns), member.Key);
            Assert.Equal(member.Arity, member.Parameters.Count);
            Assert.NotEmpty(member.UsedBy);
            Assert.All(member.Parameters, p => Assert.False(string.IsNullOrWhiteSpace(p.Name), member.Key));
            Assert.All(member.Parameters, p => Assert.False(string.IsNullOrWhiteSpace(p.Type), member.Key));
        }
    }

    /// <summary>
    /// <c>IModelDoc2.EditDelete</c> is the member the owner decided v1 refuses rather than
    /// allowlists: a mis-membered RMS-named folder is refused, never dissolved. It is recorded
    /// here so an upgrade cannot quietly change what it is, and it is <b>not</b> allowlisted.
    /// </summary>
    [Fact]
    public void EditDeleteIsRecordedAndIsNotAllowlisted()
    {
        Assert.False(Loaded.Member("IModelDoc2.EditDelete").Allowlisted);
        Assert.DoesNotContain("IModelDoc2.EditDelete", RemodelGuard.AllowedKeys);
    }

    /// <summary>
    /// Every absence carries the consequence the design draws from it, because an absence with
    /// no stated consequence is a line nobody can act on when it turns into a presence.
    /// </summary>
    [Fact]
    public void EveryAbsenceNamesItsConsequence()
    {
        Assert.NotEmpty(Loaded.Absences);
        foreach (ManifestAbsence absence in Loaded.Absences)
        {
            Assert.False(string.IsNullOrWhiteSpace(absence.Interface));
            Assert.False(string.IsNullOrWhiteSpace(absence.Consequence));
            Assert.True(
                !string.IsNullOrWhiteSpace(absence.Member) || !string.IsNullOrWhiteSpace(absence.MemberPattern),
                "an absence row names neither a member nor a member pattern");
        }
    }

    // =====================================================================================
    // Test B: workstation-only, skipped when the interop assembly is absent.
    // =====================================================================================

    /// <summary>
    /// Regenerates <c>{interface, member, arity, ordered parameter names, return type}</c> from
    /// the installed assembly by the same reflection dump that produced the fixture, and diffs.
    ///
    /// A member whose signature changed fails, naming the interface, the member and both
    /// signatures; a member that disappeared fails; a member that appeared in
    /// <c>absences</c> fails, because a design decision was made on its absence; an enum whose
    /// integer changed fails. The installed <c>assembly_version</c> is the first line of the
    /// failure, so the diff says which SOLIDWORKS is installed before it says what moved.
    ///
    /// <b>Nothing here launches SOLIDWORKS.</b> The interop assemblies are ordinary managed
    /// assemblies; only their metadata is read.
    /// </summary>
    [InteropAssembliesPresentFact]
    public void InstalledAssemblyMatchesManifest()
    {
        string redist = InstalledInterop.RedistDirectory()!;
        Assembly swconst = InstalledInterop.Load(redist, "SolidWorks.Interop.swconst");
        Assembly sldworks = InstalledInterop.Load(redist, "SolidWorks.Interop.sldworks");

        var differences = new List<string>();

        foreach (ManifestMember row in Loaded.Members)
        {
            Type? type = sldworks.GetType("SolidWorks.Interop.sldworks." + row.Interface);
            if (type == null)
            {
                differences.Add($"{row.Interface} is gone from the installed assembly ({row.Key})");
                continue;
            }

            MethodInfo[] found = type.GetMethods()
                .Where(m => string.Equals(m.Name, row.Member, StringComparison.Ordinal))
                .ToArray();

            if (found.Length == 0)
            {
                differences.Add($"{row.Key} is gone from the installed assembly; manifest had {row.Signature}");
                continue;
            }

            if (found.Length > 1)
            {
                differences.Add(
                    $"{row.Key} now has {found.Length} overloads, so the manifest's single "
                    + $"signature {row.Signature} no longer identifies it");
                continue;
            }

            string installed = InstalledInterop.SignatureOf(found[0]);
            if (!string.Equals(installed, row.Signature, StringComparison.Ordinal))
            {
                differences.Add(
                    $"{row.Interface}.{row.Member} changed signature{Environment.NewLine}"
                    + $"    manifest : {row.Signature}{Environment.NewLine}"
                    + $"    installed: {installed}");
            }
        }

        foreach (ManifestAbsence absence in Loaded.Absences)
        {
            Type? type = sldworks.GetType("SolidWorks.Interop.sldworks." + absence.Interface);
            if (type == null)
            {
                differences.Add($"{absence.Interface} is gone, so its recorded absence cannot be checked");
                continue;
            }

            string[] appeared = type.GetMembers()
                .Select(m => m.Name)
                .Distinct(StringComparer.Ordinal)
                .Where(absence.Matches)
                .OrderBy(n => n, StringComparer.Ordinal)
                .ToArray();

            if (appeared.Length > 0)
            {
                differences.Add(
                    $"{absence.Interface}.{absence.Member ?? absence.MemberPattern} was absent and "
                    + $"is now present as {string.Join(", ", appeared)}; the design depends on its "
                    + $"absence: {absence.Consequence}");
            }
        }

        foreach (ManifestEnum declared in Loaded.Enums)
        {
            Type? type = swconst.GetType("SolidWorks.Interop.swconst." + declared.Name);
            if (type == null)
            {
                differences.Add($"{declared.Name} is gone from the installed swconst assembly");
                continue;
            }

            foreach (KeyValuePair<string, int> value in declared.Values)
            {
                if (!Enum.IsDefined(type, value.Key))
                {
                    differences.Add($"{declared.Name}.{value.Key} is gone from the installed assembly");
                    continue;
                }

                int installed = (int)(object)Enum.Parse(type, value.Key);
                if (installed != value.Value)
                {
                    differences.Add(
                        $"{declared.Name}.{value.Key} is {installed} on the installed assembly and "
                        + $"{value.Value} in the manifest");
                }
            }
        }

        string installedVersion = sldworks.GetName().Version?.ToString() ?? "(none)";
        Assert.True(
            differences.Count == 0,
            $"installed SolidWorks.Interop.sldworks {installedVersion}, manifest "
            + $"{Loaded.AssemblyVersion}{Environment.NewLine}"
            + string.Join(Environment.NewLine, differences)
            + Environment.NewLine
            + "Regenerating the manifest is a deliberate, reviewed commit: the new file, the "
            + "version bump, and a note in the quickstart saying which members moved.");
    }

    /// <summary>
    /// The branch that decides whether test B runs at all: a candidate folder without both
    /// interop assemblies is not a redist folder, so the test is skipped with its reason rather
    /// than passing on a machine that checked nothing. Exercised here because the machine this
    /// runs on has a seat, so the skip path is never taken by the test itself.
    /// </summary>
    [Fact]
    public void TheInteropLocatorAnswersNothingWhenNoCandidateHoldsBothAssemblies()
    {
        Assert.Null(InstalledInterop.RedistDirectoryIn(new string?[] { null, string.Empty }));
        Assert.Null(InstalledInterop.RedistDirectoryIn(new[] { AppContext.BaseDirectory }));
    }

    // =====================================================================================
    // Loading the fixture, and finding the installed assemblies.
    // =====================================================================================

    /// <summary>
    /// A <c>[Fact]</c> that reports itself as skipped, with the reason, when the SOLIDWORKS
    /// interop assemblies are not installed. xUnit 2 decides <c>Skip</c> at discovery, which is
    /// why this is an attribute rather than a branch inside the test: a branch would report a
    /// pass and a machine with no seat would look like a machine that checked.
    /// </summary>
    private sealed class InteropAssembliesPresentFactAttribute : FactAttribute
    {
        public InteropAssembliesPresentFactAttribute()
        {
            if (InstalledInterop.RedistDirectory() == null)
            {
                Skip = "SolidWorks.Interop.sldworks.dll is not installed (looked in "
                    + "%SWREVIEW_SW_REDIST% and the default SOLIDWORKS api\\redist folder), so the "
                    + "manifest cannot be regenerated from the installed assembly here.";
            }
        }
    }

    private static class InstalledInterop
    {
        private const string SldWorks = "SolidWorks.Interop.sldworks";
        private const string SwConst = "SolidWorks.Interop.swconst";

        /// <summary>
        /// The redist folder holding both interop assemblies, or null when neither candidate
        /// has them. <c>SWREVIEW_SW_REDIST</c> overrides, exactly as <c>$(SwRedist)</c> does for
        /// the build.
        /// </summary>
        public static string? RedistDirectory() => RedistDirectoryIn(Candidates());

        /// <summary>
        /// The locator's decision, over a candidate list, so the "nothing is installed" branch -
        /// the one that decides whether test B runs or is skipped - is itself testable on a
        /// machine that does have a seat.
        /// </summary>
        public static string? RedistDirectoryIn(IEnumerable<string?> candidates)
        {
            foreach (string? candidate in candidates)
            {
                if (string.IsNullOrWhiteSpace(candidate))
                {
                    continue;
                }

                if (File.Exists(Path.Combine(candidate!, SldWorks + ".dll"))
                    && File.Exists(Path.Combine(candidate!, SwConst + ".dll")))
                {
                    return candidate;
                }
            }

            return null;
        }

        private static IEnumerable<string?> Candidates()
        {
            yield return Environment.GetEnvironmentVariable("SWREVIEW_SW_REDIST");

            foreach (Environment.SpecialFolder folder in new[]
                     {
                         Environment.SpecialFolder.ProgramFiles,
                         Environment.SpecialFolder.ProgramFilesX86,
                     })
            {
                string root = Environment.GetFolderPath(folder);
                if (!string.IsNullOrEmpty(root))
                {
                    yield return Path.Combine(root, "SOLIDWORKS Corp", "SOLIDWORKS", "api", "redist");
                }
            }
        }

        public static Assembly Load(string redist, string name) =>
            Assembly.LoadFrom(Path.Combine(redist, name + ".dll"));

        /// <summary>
        /// The one spelling of a signature both halves of this test compare, so a difference is
        /// a difference of the signature and never of the formatting.
        /// </summary>
        public static string SignatureOf(MethodInfo method)
        {
            var text = new StringBuilder();
            text.Append('(');
            ParameterInfo[] parameters = method.GetParameters();
            for (int i = 0; i < parameters.Length; i++)
            {
                if (i > 0)
                {
                    text.Append(", ");
                }

                text.Append(parameters[i].Name).Append(':').Append(parameters[i].ParameterType.FullName);
            }

            text.Append(") -> ").Append(method.ReturnType.FullName);
            return text.ToString();
        }
    }

    // ------------------------------------------------------------------ the fixture model

    private sealed class Manifest
    {
        public string Schema { get; private set; } = string.Empty;

        public string Assembly { get; private set; } = string.Empty;

        public string AssemblyVersion { get; private set; } = string.Empty;

        public string SwconstVersion { get; private set; } = string.Empty;

        public string Product { get; private set; } = string.Empty;

        public IReadOnlyList<ManifestMember> Members { get; private set; } = Array.Empty<ManifestMember>();

        public IReadOnlyList<ManifestEnum> Enums { get; private set; } = Array.Empty<ManifestEnum>();

        public IReadOnlyList<ManifestAbsence> Absences { get; private set; } = Array.Empty<ManifestAbsence>();

        public ManifestMember Member(string key) =>
            Members.SingleOrDefault(m => string.Equals(m.Key, key, StringComparison.Ordinal))
            ?? throw new InvalidOperationException(
                $"{key} has no row in {FixturePath}. Every interop member the re-modeler calls "
                + "needs one, or nothing notices when its signature moves.");

        public int Enum(string enumName, string memberName)
        {
            ManifestEnum declared = Enums.SingleOrDefault(e => string.Equals(e.Name, enumName, StringComparison.Ordinal))
                ?? throw new InvalidOperationException($"{enumName} has no row in {FixturePath}.");

            return declared.Values.TryGetValue(memberName, out int value)
                ? value
                : throw new InvalidOperationException($"{enumName}.{memberName} has no value in {FixturePath}.");
        }

        public static Manifest Load()
        {
            string path = Path.Combine(AppContext.BaseDirectory, FixturePath);
            if (!File.Exists(path))
            {
                throw new FileNotFoundException(
                    $"the frozen interop-surface manifest is missing at {path}; it is checked in at "
                    + $"extractor/SwReview.Extractor.Tests/{FixturePath.Replace('\\', '/')}",
                    path);
            }

            using (JsonDocument document = JsonDocument.Parse(File.ReadAllText(path)))
            {
                JsonElement root = document.RootElement;
                return new Manifest
                {
                    Schema = root.GetProperty("manifest_schema").GetString() ?? string.Empty,
                    Assembly = root.GetProperty("assembly").GetString() ?? string.Empty,
                    AssemblyVersion = root.GetProperty("assembly_version").GetString() ?? string.Empty,
                    SwconstVersion = root.GetProperty("swconst_version").GetString() ?? string.Empty,
                    Product = root.GetProperty("product").GetString() ?? string.Empty,
                    Members = root.GetProperty("members").EnumerateArray().Select(ManifestMember.Read).ToArray(),
                    Enums = root.GetProperty("enums").EnumerateArray().Select(ManifestEnum.Read).ToArray(),
                    Absences = root.GetProperty("absences").EnumerateArray().Select(ManifestAbsence.Read).ToArray(),
                };
            }
        }
    }

    private sealed class ManifestMember
    {
        public string Interface { get; private set; } = string.Empty;

        public string Member { get; private set; } = string.Empty;

        public string Kind { get; private set; } = string.Empty;

        public int Arity { get; private set; }

        public IReadOnlyList<ManifestParameter> Parameters { get; private set; } =
            Array.Empty<ManifestParameter>();

        public string Returns { get; private set; } = string.Empty;

        public IReadOnlyList<string> UsedBy { get; private set; } = Array.Empty<string>();

        public bool Allowlisted { get; private set; }

        public string Key => Interface + "." + Member;

        /// <summary>The one spelling both halves of the manifest test compare.</summary>
        public string Signature =>
            "(" + string.Join(", ", Parameters.Select(p => p.Name + ":" + p.Type)) + ") -> " + Returns;

        public static ManifestMember Read(JsonElement element) => new ManifestMember
        {
            Interface = element.GetProperty("interface").GetString() ?? string.Empty,
            Member = element.GetProperty("member").GetString() ?? string.Empty,
            Kind = element.GetProperty("kind").GetString() ?? string.Empty,
            Arity = element.GetProperty("arity").GetInt32(),
            Parameters = element.GetProperty("parameters").EnumerateArray()
                .Select(ManifestParameter.Read).ToArray(),
            Returns = element.GetProperty("returns").GetString() ?? string.Empty,
            UsedBy = element.GetProperty("used_by").EnumerateArray()
                .Select(u => u.GetString() ?? string.Empty).ToArray(),
            Allowlisted = element.GetProperty("allowlisted").GetBoolean(),
        };
    }

    private sealed class ManifestParameter
    {
        public string Name { get; private set; } = string.Empty;

        public string Type { get; private set; } = string.Empty;

        public static ManifestParameter Read(JsonElement element) => new ManifestParameter
        {
            Name = element.GetProperty("name").GetString() ?? string.Empty,
            Type = element.GetProperty("type").GetString() ?? string.Empty,
        };
    }

    private sealed class ManifestEnum
    {
        public string Name { get; private set; } = string.Empty;

        public IReadOnlyDictionary<string, int> Values { get; private set; } =
            new Dictionary<string, int>(StringComparer.Ordinal);

        public static ManifestEnum Read(JsonElement element)
        {
            var values = new Dictionary<string, int>(StringComparer.Ordinal);
            foreach (JsonProperty value in element.GetProperty("values").EnumerateObject())
            {
                values.Add(value.Name, value.Value.GetInt32());
            }

            return new ManifestEnum
            {
                Name = element.GetProperty("enum").GetString() ?? string.Empty,
                Values = values,
            };
        }
    }

    private sealed class ManifestAbsence
    {
        public string Interface { get; private set; } = string.Empty;

        public string? Member { get; private set; }

        public string? MemberPattern { get; private set; }

        /// <summary>
        /// Names a pattern matches that are <b>not</b> the member the design depends on being
        /// absent. <c>IFeatureManager.GetPlasticsShellType</c> matches <c>*Shell*</c> and is a
        /// Plastics query, not a shell creator; recording it keeps the broad pattern, so a new
        /// <c>InsertShell</c> still fails the test.
        /// </summary>
        public IReadOnlyList<string> Except { get; private set; } = Array.Empty<string>();

        public string Consequence { get; private set; } = string.Empty;

        public bool Matches(string memberName)
        {
            if (Except.Contains(memberName, StringComparer.Ordinal))
            {
                return false;
            }

            if (Member != null)
            {
                return string.Equals(Member, memberName, StringComparison.Ordinal);
            }

            string pattern = MemberPattern ?? string.Empty;
            string core = pattern.Trim('*');
            return pattern.StartsWith("*", StringComparison.Ordinal)
                && pattern.EndsWith("*", StringComparison.Ordinal)
                && memberName.IndexOf(core, StringComparison.Ordinal) >= 0;
        }

        public static ManifestAbsence Read(JsonElement element) => new ManifestAbsence
        {
            Interface = element.GetProperty("interface").GetString() ?? string.Empty,
            Member = element.TryGetProperty("member", out JsonElement member) ? member.GetString() : null,
            MemberPattern = element.TryGetProperty("member_pattern", out JsonElement pattern)
                ? pattern.GetString()
                : null,
            Except = element.TryGetProperty("except", out JsonElement except)
                ? except.EnumerateArray().Select(e => e.GetString() ?? string.Empty).ToArray()
                : Array.Empty<string>(),
            Consequence = element.GetProperty("consequence").GetString() ?? string.Empty,
        };
    }
}
