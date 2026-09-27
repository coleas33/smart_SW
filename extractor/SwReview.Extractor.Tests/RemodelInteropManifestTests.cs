using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
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
    // T152's manifest half and T156 (004 build order, lane C): the seat adapter's surface.
    // =====================================================================================

    /// <summary>
    /// T156. The interop members the production seat adapter (T153 to T155) calls that the
    /// fixture did not record, pinned by value. Every one is a read, or a property set on a
    /// throwaway open request, so none is allowlisted: the guard's list changes only as the 004
    /// contracts say, and they say nothing here. <c>InstalledAssemblyMatchesManifest</c> checks
    /// each signature against the installed interop, like every other row.
    /// </summary>
    private static readonly string[] SeatAdapterAdditions =
    {
        // The copy adapter's plumbing (T153): every IModelDocExtension member is reached
        // through get_Extension and every IFeatureManager member through get_FeatureManager.
        "IModelDoc2.get_Extension",
        "IModelDoc2.get_FeatureManager",
        "IModelDoc2.GetEquationMgr",
        "IModelDoc2.GetUnits",
        "IModelDocExtension.GetPersistReference3",
        "IFeatureManager.GetFeatures",

        // The material's configuration (IGeometrySource.GetMaterialName reads the active one).
        "IModelDoc2.get_ConfigurationManager",
        "IConfigurationManager.get_ActiveConfiguration",
        "IConfiguration.get_Name",

        // A folder's members, for the rms_named_folders signal (T153 and T154's shared reader).
        // GetFeatureCount is the count the members are read against, found by the cross-check
        // when lane B merged (default taken 2026-09-27, the owner may revise).
        "IFeature.GetSpecificFeature2",
        "IFeatureFolder.GetFeatures",
        "IFeatureFolder.GetFeatureCount",

        // The copy's open request (T155's open-options helper, shared with remodel.open_copy).
        "ISldWorks.GetOpenDocSpec",
        "IDocumentSpecification.set_DocumentType",
        "IDocumentSpecification.set_Silent",
        "IDocumentSpecification.set_LoadModel",
        "IDocumentSpecification.set_ReadOnly",
        "IDocumentSpecification.set_ViewOnly",
        "IDocumentSpecification.get_Error",
        "IDocumentSpecification.get_Warning",
    };

    /// <summary>
    /// T156: each addition has a builder row and a manifest row, and neither is allowlisted, so
    /// <c>CodeMatchesManifest</c> compares its signature and its allowlist flag like any other.
    /// </summary>
    [Fact]
    public void EveryMemberTheSeatAdapterAddsHasARowAndIsNotAllowlisted()
    {
        Assert.Equal(
            SeatAdapterAdditions.Length,
            SeatAdapterAdditions.Distinct(StringComparer.Ordinal).Count());

        var builders = RemodelInteropSurface.Calls.ToDictionary(c => c.Key, StringComparer.Ordinal);
        var missing = new List<string>();
        foreach (string key in SeatAdapterAdditions)
        {
            if (!builders.TryGetValue(key, out RemodelInteropCall? call)
                || call == null
                || !Loaded.Members.Any(m => string.Equals(m.Key, key, StringComparison.Ordinal)))
            {
                missing.Add(key);
                continue;
            }

            Assert.False(call.Allowlisted, key + " is a read and is not allowlisted in the builder table");
            Assert.False(Loaded.Member(key).Allowlisted, key + " is a read and is not allowlisted in the manifest");
            Assert.DoesNotContain(key, RemodelGuard.AllowedKeys);
        }

        Assert.True(
            missing.Count == 0,
            "the seat adapter calls interop members with no builder row or no manifest row, so "
            + "nothing would notice if their signatures moved: " + string.Join(", ", missing));
    }

    /// <summary>
    /// The constants the seat adapter writes by their swconst names and the manifest did not
    /// record (004 build order, the lane B and C cross-check; default taken 2026-09-27, the owner
    /// may revise): <c>swAllBodies</c>, the body type the mesh and graphics rows ask
    /// <c>GetBodies2</c> for; <c>swPersistReferencedObject_Invalid</c>, what a persist ref that
    /// does not decode answers without asking SOLIDWORKS; and every <c>swLengthUnit_e</c> member,
    /// the keys of <see cref="RemodelLengthUnits"/>' table. Each is pinned here as an integer,
    /// test B holds it to the installed swconst, and the length-unit table is read through the
    /// manifest's integers, so a unit whose integer moved under its name cannot be named wrong
    /// silently.
    /// </summary>
    [Fact]
    public void EveryConstantTheSeatAdapterComposesHasAnEnumRow()
    {
        Assert.Equal(-1, Loaded.Enum("swBodyType_e", "swAllBodies"));
        Assert.Equal(1, Loaded.Enum("swPersistReferencedObjectStates_e", "swPersistReferencedObject_Invalid"));

        var tokens = new Dictionary<string, (int Value, string Token)>(StringComparer.Ordinal)
        {
            ["swMM"] = (0, "mm"),
            ["swCM"] = (1, "cm"),
            ["swMETER"] = (2, "m"),
            ["swINCHES"] = (3, "in"),
            ["swFEET"] = (4, "ft"),
            ["swFEETINCHES"] = (5, "ft-in"),
            ["swANGSTROM"] = (6, "angstrom"),
            ["swNANOMETER"] = (7, "nm"),
            ["swMICRON"] = (8, "um"),
            ["swMIL"] = (9, "mil"),
            ["swUIN"] = (10, "uin"),
        };

        ManifestEnum units = Loaded.Enums.Single(e => string.Equals(e.Name, "swLengthUnit_e", StringComparison.Ordinal));
        Assert.Equal(
            tokens.Keys.OrderBy(name => name, StringComparer.Ordinal),
            units.Values.Keys.OrderBy(name => name, StringComparer.Ordinal));
        foreach (KeyValuePair<string, (int Value, string Token)> unit in tokens)
        {
            int recorded = Loaded.Enum("swLengthUnit_e", unit.Key);
            Assert.Equal(unit.Value.Value, recorded);
            Assert.Equal(unit.Value.Token, RemodelLengthUnits.TokenFor(recorded));
        }
    }

    /// <summary>
    /// T154's reads are exactly <see cref="RemodelScopeProbe.ProbeSurface"/> (the
    /// <c>scope_signals</c> table plus the three protocol reads), and the resolve pair every
    /// change command makes is <see cref="RemodelSession"/>'s: each gated name has a row, read as
    /// the member itself or its <c>get_</c> accessor (the probe gates
    /// <c>Is3DInterconnectFeature</c>, a property).
    /// </summary>
    [Fact]
    public void EveryMemberTheScopeProbeGatesHasARow()
    {
        string[] gated = RemodelScopeProbe.ProbeSurface
            .Concat(new[] { RemodelSession.ResolveMember, RemodelSession.NameMember })
            .ToArray();
        Assert.Equal(15, gated.Length);

        HashSet<string> recorded = RecordedMembers;
        string[] unrecorded = gated
            .Where(member => !InteropMemberScan.Candidates(member, MemberUse.Read).Any(recorded.Contains))
            .ToArray();
        Assert.True(
            unrecorded.Length == 0,
            "the remodel seam gates members the frozen manifest does not record: " + string.Join(", ", unrecorded));
    }

    /// <summary>
    /// The audit of T152 (004 build order, lane C): every interop member the seat adapter's
    /// source names has a row. <see cref="CodeMatchesManifest"/> compares the manifest with a
    /// hand-written table, so a member called directly and never added to the table would pass
    /// it; this reads the adapter's own source instead, by the file scan
    /// <see cref="DrawingFamilyReadAuditTests"/> runs.
    ///
    /// What it can and cannot see is <see cref="SeatAdapterScan"/>'s to say; the short of it is
    /// that it knows a member's name and how it is used, never the interface it is called on.
    /// </summary>
    [Fact]
    public void EveryInteropMemberTheSeatAdapterSourceNamesHasARow()
    {
        string[] unrecorded = SeatAdapterScan.Files()
            .SelectMany(file => SeatAdapterScan.UnrecordedIn(File.ReadAllText(file))
                .Select(name => (Name: name, Where: Path.GetFileName(file))))
            .Where(found => !SeatAdapterScan.NamedExceptions.ContainsKey(found.Name))
            .Select(found => $"{found.Name} in {found.Where}")
            .Distinct(StringComparer.Ordinal)
            .OrderBy(found => found, StringComparer.Ordinal)
            .ToArray();

        Assert.True(
            unrecorded.Length == 0,
            "the seat adapter's source names interop members the frozen manifest does not record, "
            + "so nothing would notice if their signatures moved. Add each one's row to "
            + "RemodelInteropSurface and to the fixture (by reflection over the installed interop, "
            + "contracts/interop-manifest.md), or, for a name that is not a SOLIDWORKS call, a "
            + "named exception with its reason: " + string.Join(", ", unrecorded));
    }

    /// <summary>
    /// A floor, so the audit cannot pass by reading nothing: the shared classes are read, the
    /// interop calls they make are found, and a file declaring one of the build order's adapter
    /// classes is read wherever it is, so a move cannot quietly shrink the scan.
    /// </summary>
    [Fact]
    public void TheSeatAdapterScanReadsTheAdapterSource()
    {
        IReadOnlyList<string> files = SeatAdapterScan.Files();
        foreach (string shared in SeatAdapterScan.SharedFiles)
        {
            Assert.True(
                files.Any(file => file.EndsWith(Path.DirectorySeparatorChar + shared, StringComparison.OrdinalIgnoreCase)),
                shared + " is not among the files the audit reads; a shared class that moved is one it no longer audits.");
        }

        foreach (string file in DrawingFamilyReadAuditTests.ProductSourceFiles())
        {
            string code = InteropMemberScan.CodeOnly(File.ReadAllText(file));
            foreach (string adapter in SeatAdapterScan.AdapterClasses)
            {
                if (Regex.IsMatch(code, @"\b(?:class|struct|record)\s+" + adapter + @"\b"))
                {
                    Assert.True(
                        SeatAdapterScan.IsScanned(file),
                        $"{adapter} is declared in {file}, which the seat adapter audit does not read.");
                }
            }
        }

        var named = new HashSet<string>(
            files.SelectMany(file => InteropMemberScan.Accesses(File.ReadAllText(file)))
                .SelectMany(access => InteropMemberScan.Candidates(access.Name, access.Use)),
            StringComparer.Ordinal);
        foreach (string member in new[]
                 {
                     "GetCount", "get_Equation", "Add3", "Add2", "set_Equation", "Delete",
                     "Recalculate", "set_AccuracyLevel", "set_UseSystemUnits", "get_Volume", "get_CenterOfMass",
                 })
        {
            Assert.Contains(member, named);
        }
    }

    /// <summary>
    /// Each named exception is still needed: still a name the scan finds in the adapter's source,
    /// still declared by the interop and still without a row. One that is not hides nothing today
    /// and would hide a real call tomorrow.
    /// </summary>
    [Fact]
    public void EveryNamedExceptionIsStillAnUnrecordedInteropNameTheScanFinds()
    {
        var unrecorded = new HashSet<string>(
            SeatAdapterScan.Files().SelectMany(file => SeatAdapterScan.UnrecordedIn(File.ReadAllText(file))),
            StringComparer.Ordinal);

        Assert.NotEmpty(SeatAdapterScan.NamedExceptions);
        foreach (KeyValuePair<string, string> exception in SeatAdapterScan.NamedExceptions)
        {
            Assert.True(
                unrecorded.Contains(exception.Key),
                $"the named exception '{exception.Key}' is no longer an unrecorded interop name in the "
                + "seat adapter's source; remove it.");
            Assert.False(string.IsNullOrWhiteSpace(exception.Value), exception.Key);
        }
    }

    /// <summary>The audit's decision on single lines, against the real interop and the real fixture.</summary>
    [Theory]
    [InlineData("document.GetPathName();", "")]
    [InlineData("document.GetTitle();", "GetTitle")]
    [InlineData("feature.Name = name;", "")]
    [InlineData("specification.FileName = path;", "FileName")]
    [InlineData("int count = features.Count;", "Count")]
    [InlineData("reader.NotASolidWorksMember();", "")]
    [InlineData("// document.GetTitle();", "")]
    public void TheAuditFlagsANameTheInteropDeclaresAndNoRowRecords(string source, string expected)
    {
        Assert.Equal(expected, string.Join("|", SeatAdapterScan.UnrecordedIn(source)));
    }

    /// <summary>
    /// The scanner itself: comments are dropped and strings kept (a name in a message is read,
    /// which can only add to what the audit asks for), a string or a character literal is never
    /// mistaken for a comment, directives name namespaces rather than members, and the use of
    /// each member decides the accessor it names.
    /// </summary>
    [Theory]
    [InlineData("x.Name = y;", "Name:Assign")]
    [InlineData("x.Name == y", "Name:Read")]
    [InlineData("x.Name != y && x.Count <= 2", "Name:Read|Count:Read")]
    [InlineData("x.Count += 1; x.Mask |= 4;", "Count:CompoundAssign|Mask:CompoundAssign")]
    [InlineData("Func<int> f = () => x.Value;", "Value:Read")]
    [InlineData("a?.B?.C()", "B:Read|C:Read")]
    [InlineData("x\n    .Chained()\n    .Again = 1;", "Chained:Read|Again:Assign")]
    [InlineData("list.Cast<object>()", "Cast:Read")]
    [InlineData("double d = 1.5 + 2.0e3; y.Shown", "Shown:Read")]
    [InlineData("// x.Hidden();\ny.Shown", "Shown:Read")]
    [InlineData("/// <c>IModelDoc2.Hidden</c>\ny.Shown", "Shown:Read")]
    [InlineData("/* x.Hidden\n z.Hidden */ y.Shown", "Shown:Read")]
    [InlineData("y.Shown(); // x.Hidden()", "Shown:Read")]
    [InlineData("var s = \"http://a.InString\"; y.Shown", "InString:Read|Shown:Read")]
    [InlineData("var s = \"say \\\"// x.InString\\\"\"; y.Shown", "InString:Read|Shown:Read")]
    [InlineData("var s = @\"a\"\"// x.InString\"; y.Shown", "InString:Read|Shown:Read")]
    [InlineData("var s = $@\"{a.Hole}\"\"//\"; y.Shown", "Hole:Read|Shown:Read")]
    [InlineData("var c = '\"'; y.Shown // x.Hidden", "Shown:Read")]
    [InlineData("var c = '\\''; y.Shown // x.Hidden", "Shown:Read")]
    [InlineData("using SolidWorks.Interop.sldworks;\nusing Alias = System.IO.Path;\nnamespace A.B;\ny.Shown", "Shown:Read")]
    [InlineData("using (var stream = File.Open(p)) { stream.Shown(); }", "Open:Read|Shown:Read")]
    public void TheScannerReadsEachMemberAccessAndHowItIsUsed(string source, string expected)
    {
        Assert.Equal(
            expected,
            string.Join("|", InteropMemberScan.Accesses(source).Select(access => access.Name + ":" + access.Use)));
    }

    [Theory]
    [InlineData(MemberUse.Read, "Volume|get_Volume")]
    [InlineData(MemberUse.Assign, "set_Volume")]
    [InlineData(MemberUse.CompoundAssign, "get_Volume|set_Volume")]
    public void EachUseNamesTheAccessorsItCanReach(MemberUse use, string expected)
    {
        Assert.Equal(expected, string.Join("|", InteropMemberScan.Candidates("Volume", use)));
    }

    /// <summary>Every member name the fixture records, whatever its interface.</summary>
    private static HashSet<string> RecordedMembers =>
        new HashSet<string>(Loaded.Members.Select(m => m.Member), StringComparer.Ordinal);

    /// <summary>How a member access uses the member, which decides the accessor it can reach.</summary>
    public enum MemberUse
    {
        /// <summary>A call, a property read, or a method group: the member itself or its getter.</summary>
        Read,

        /// <summary><c>x.Member = value</c>: the setter.</summary>
        Assign,

        /// <summary><c>x.Member += value</c> and the other compound assignments: the getter and the setter.</summary>
        CompoundAssign,
    }

    /// <summary>
    /// Member accesses in C# source, read without a compiler: <c>.Name</c> anywhere outside a
    /// comment, with the use that follows it. Strings are kept rather than blanked, because an
    /// interpolated string holds code and a name inside a message can only make the audit ask
    /// for more, never less.
    /// </summary>
    internal static class InteropMemberScan
    {
        private static readonly Regex Access = new Regex(
            @"\.(?<name>[A-Za-z_][A-Za-z0-9_]*)(?<assign>\s*(?<op><<|>>|\?\?|[+\-*/%&|^])?=(?![=>]))?",
            RegexOptions.Compiled);

        /// <summary>
        /// <c>using</c> directives (an alias included, a <c>using (...)</c> statement not) and
        /// <c>namespace</c> declarations name namespaces, not members.
        /// </summary>
        private static readonly Regex Directive = new Regex(
            @"^[ \t]*(?:(?:global[ \t]+)?using[ \t]+[^;(\r\n]*;|namespace[ \t]+[A-Za-z0-9_.]+)",
            RegexOptions.Compiled | RegexOptions.Multiline);

        /// <summary>The interop names a use of <paramref name="name"/> can reach.</summary>
        public static IReadOnlyList<string> Candidates(string name, MemberUse use)
        {
            switch (use)
            {
                case MemberUse.Assign:
                    return new[] { "set_" + name };
                case MemberUse.CompoundAssign:
                    return new[] { "get_" + name, "set_" + name };
                default:
                    return new[] { name, "get_" + name };
            }
        }

        public static IEnumerable<(string Name, MemberUse Use)> Accesses(string source)
        {
            foreach (Match match in Access.Matches(CodeOnly(source)))
            {
                MemberUse use = !match.Groups["assign"].Success
                    ? MemberUse.Read
                    : match.Groups["op"].Success ? MemberUse.CompoundAssign : MemberUse.Assign;
                yield return (match.Groups["name"].Value, use);
            }
        }

        /// <summary>
        /// The source with its comments and directives removed. A string or character literal is
        /// copied as it stands, and only so that a <c>//</c> or a quote inside it is not taken for
        /// the start of a comment or of another literal.
        /// </summary>
        public static string CodeOnly(string source)
        {
            var code = new StringBuilder(source.Length);
            int at = 0;
            while (at < source.Length)
            {
                char current = source[at];
                char next = at + 1 < source.Length ? source[at + 1] : '\0';

                if (current == '/' && next == '/')
                {
                    while (at < source.Length && source[at] != '\n')
                    {
                        at++;
                    }

                    continue;
                }

                if (current == '/' && next == '*')
                {
                    int close = source.IndexOf("*/", at + 2, StringComparison.Ordinal);
                    at = close < 0 ? source.Length : close + 2;
                    code.Append(' ');
                    continue;
                }

                if (current == '"' || current == '\'')
                {
                    int end = EndOfLiteral(source, at);
                    code.Append(source, at, end - at);
                    at = end;
                    continue;
                }

                code.Append(current);
                at++;
            }

            return Directive.Replace(code.ToString(), string.Empty);
        }

        /// <summary>
        /// Where the literal opening at <paramref name="start"/> ends: a verbatim string
        /// (<c>@"</c>, <c>$@"</c>, <c>@$"</c>) at its unpaired closing quote; a regular string
        /// or a character literal at its unescaped closing quote, or at the end of the line when
        /// it has none.
        /// </summary>
        private static int EndOfLiteral(string source, int start)
        {
            char quote = source[start];
            bool verbatim = quote == '"'
                && ((start >= 1 && source[start - 1] == '@')
                    || (start >= 2 && source[start - 1] == '$' && source[start - 2] == '@'));

            int at = start + 1;
            while (at < source.Length)
            {
                char current = source[at];
                if (verbatim)
                {
                    if (current == '"')
                    {
                        if (at + 1 < source.Length && source[at + 1] == '"')
                        {
                            at += 2;
                            continue;
                        }

                        return at + 1;
                    }
                }
                else
                {
                    if (current == '\\')
                    {
                        at += 2;
                        continue;
                    }

                    if (current == quote)
                    {
                        return at + 1;
                    }

                    if (current == '\n')
                    {
                        return at;
                    }
                }

                at++;
            }

            return source.Length;
        }
    }

    /// <summary>
    /// The seat adapter's source as the audit reads it (004 build order, lane C).
    ///
    /// <b>What it reads.</b> The files under <see cref="SeatFolder"/> (lane B's adapters) and
    /// <see cref="SharedFiles"/> (lane A's ungated <c>IEquationTarget</c> and
    /// <c>IMassPropertyReading</c> classes, which the copy adapter uses directly, and lane B's
    /// extractor-side files the adapters share with the probe host), found by the
    /// product-source scan <see cref="DrawingFamilyReadAuditTests"/> runs.
    ///
    /// <b>What it decides.</b> A name that some public interface of the interop the product is
    /// built against declares - as itself, or as the accessor its use reaches - and that no
    /// manifest row records, on any interface. So it catches a SOLIDWORKS call with no frozen
    /// signature at all; it <b>cannot</b> see which interface a name is called on, so a name
    /// recorded on one interface passes when it is called on another, and an indexed property
    /// set (<c>x.Member[i] = v</c>) is read as a get. A name that is not a SOLIDWORKS call but
    /// matches one is a <see cref="NamedExceptions"/> entry with its reason, and
    /// <c>EveryNamedExceptionIsStillAnUnrecordedInteropNameTheScanFinds</c> keeps each one
    /// needed.
    /// </summary>
    internal static class SeatAdapterScan
    {
        /// <summary>Lane B's folder, relative to the extractor folder. Absent until lane B lands.</summary>
        public static readonly string SeatFolder = Path.Combine("SwReview.AddIn", "Remodel", "Seat");

        /// <summary>
        /// The shared classes outside <see cref="SeatFolder"/>, relative to the extractor folder:
        /// lane A's two, and lane B's three the adapters share with the probe host - the toggle
        /// mapping, the What's Wrong element reading and the pure length-unit table, read so that
        /// an interop call added to any of them later is audited too (default taken 2026-09-27,
        /// the owner may revise).
        /// </summary>
        public static readonly string[] SharedFiles =
        {
            Path.Combine("SwReview.Extractor", "Rms", "SwEquationManager.cs"),
            Path.Combine("SwReview.Extractor", "Rms", "SwMassProperty.cs"),
            Path.Combine("SwReview.Extractor", "Rms", "SwRemodelToggleHost.cs"),
            Path.Combine("SwReview.Extractor", "Rms", "RemodelWhatsWrong.cs"),
            Path.Combine("SwReview.Extractor", "Rms", "RemodelLengthUnits.cs"),
        };

        /// <summary>The adapter classes the build order names for lane B; each must be declared where the audit reads.</summary>
        public static readonly string[] AdapterClasses =
        {
            "SwScopeSignalReader",
            "SwRemodelCopyDocument",
            "SwRemodelProbeSource",
            "SwRemodelBridgeSeat",
            "CopyOpenSpecification",
        };

        /// <summary>Names the scan finds that are not SOLIDWORKS calls, each with where and why.</summary>
        public static readonly IReadOnlyDictionary<string, string> NamedExceptions =
            new Dictionary<string, string>(StringComparer.Ordinal)
            {
                ["Length"] = "SwMassProperty.cs: System.Array.Length, the length of the SAFEARRAY a triple is "
                    + "read from; no interop property named Length is read",

                // Lane B's, found when its files merged (defaults taken 2026-09-27, the owner may revise).
                ["Add"] = "SwScopeSignalReader.cs, SwRemodelReads.cs and RemodelWhatsWrong.cs: List<T>.Add, "
                    + "collecting what was read; the adapter writes a custom property with "
                    + "ICustomPropertyManager.Add3, which has its row, and calls no interop Add",
                ["Features"] = "SwScopeSignalReader.cs and SwRemodelCopyDocument.cs: SwRemodelReads.Features, "
                    + "the adapter's own walk over IFeatureManager.GetFeatures, which has its row; no "
                    + "interop Features member is read",
                ["GetBodyCount"] = "SwRemodelCopyDocument.cs and SwRemodelProbeSource.cs: "
                    + "IScopeSignalSource.GetBodyCount, the product's own interface, answered by "
                    + "SwScopeSignalReader from IPartDoc.GetBodies2, which has its row",
                ["Message"] = "SwRemodelBridgeSeat.cs: Exception.Message, the refusal's text carried into "
                    + "the ArgumentException; no interop Message member is read",
            };

        private static readonly Lazy<HashSet<string>> InteropMemberNames = new Lazy<HashSet<string>>(() =>
            new HashSet<string>(
                typeof(SolidWorks.Interop.sldworks.IModelDoc2).Assembly.GetExportedTypes()
                    .Where(type => type.IsInterface)
                    .SelectMany(type => type.GetMethods())
                    .Select(method => method.Name),
                StringComparer.Ordinal));

        public static bool IsScanned(string file) =>
            SharedFiles.Any(shared => file.EndsWith(Path.DirectorySeparatorChar + shared, StringComparison.OrdinalIgnoreCase))
            || file.IndexOf(
                Path.DirectorySeparatorChar + SeatFolder + Path.DirectorySeparatorChar,
                StringComparison.OrdinalIgnoreCase) >= 0;

        public static IReadOnlyList<string> Files() =>
            DrawingFamilyReadAuditTests.ProductSourceFiles().Where(IsScanned).ToList();

        /// <summary>
        /// The names in <paramref name="source"/> the interop declares and no row records, in the
        /// order they occur, each once. Named exceptions are not removed here, so the staleness
        /// case can see them.
        /// </summary>
        public static IReadOnlyList<string> UnrecordedIn(string source)
        {
            HashSet<string> recorded = RecordedMembers;
            return InteropMemberScan.Accesses(source)
                .Where(access =>
                {
                    IReadOnlyList<string> reachable = InteropMemberScan.Candidates(access.Name, access.Use);
                    return reachable.Any(InteropMemberNames.Value.Contains) && !reachable.Any(recorded.Contains);
                })
                .Select(access => access.Name)
                .Distinct(StringComparer.Ordinal)
                .ToList();
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
    ///
    /// The folders are the test's own. The test host's folder used to stand in for "neither", but
    /// it holds a copy of both interops since the test project references them with
    /// <c>Private=true</c> (004 build order, lane A), so it is now a redist folder by this rule.
    /// </summary>
    [Fact]
    public void TheInteropLocatorAnswersNothingWhenNoCandidateHoldsBothAssemblies()
    {
        Assert.Null(InstalledInterop.RedistDirectoryIn(new string?[] { null, string.Empty }));

        string neither = Path.Combine(Path.GetTempPath(), "swreview-locator-neither-" + Guid.NewGuid().ToString("N"));
        string onlyOne = Path.Combine(Path.GetTempPath(), "swreview-locator-one-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(neither);
        Directory.CreateDirectory(onlyOne);
        try
        {
            File.WriteAllText(Path.Combine(onlyOne, "SolidWorks.Interop.sldworks.dll"), string.Empty);

            Assert.Null(InstalledInterop.RedistDirectoryIn(new[] { neither }));
            Assert.Null(InstalledInterop.RedistDirectoryIn(new[] { onlyOne }));
            Assert.Null(InstalledInterop.RedistDirectoryIn(new[] { neither, onlyOne }));
        }
        finally
        {
            Directory.Delete(neither, recursive: true);
            Directory.Delete(onlyOne, recursive: true);
        }
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
    internal sealed class InteropAssembliesPresentFactAttribute : FactAttribute
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

    internal static class InstalledInterop
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
