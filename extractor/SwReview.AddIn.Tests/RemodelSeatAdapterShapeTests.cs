using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.RegularExpressions;
using SolidWorks.Interop.sldworks;
using SwReview.AddIn.Remodel;
using SwReview.AddIn.Remodel.Seat;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Tests;
using Xunit;
using ExtractorSeat = SwReview.Extractor.Rms.IRemodelSeat;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 004, T152's reflection cases for the seat adapter (build order lane B; T153 to T155).
///
/// Three properties, each read off the classes themselves rather than trusted:
/// <list type="number">
/// <item>each adapter class implements exactly the interfaces it is named for, and is built from
/// the SOLIDWORKS objects alone;</item>
/// <item>none takes or holds a <c>SwGate</c>, an <c>ICallGuard</c> or a <c>RemodelScope</c>, and
/// none names one in its code: the bridge gates the adapter from outside (T153's amendment), and
/// a gate inside would gate each call twice and log a bare write key;</item>
/// <item>nothing takes a document path it did not create: the only path-taking members are the
/// interface members that name one, and each of those is the copy's own path or the engineer's
/// open source, read and never opened.</item>
/// </list>
/// Plus the "written once" rules: the equation and mass-property mappings are lane A's shared
/// classes, the toggles are <see cref="SwRemodelToggleHost"/>, and both opens of a copy state their
/// flags through <see cref="CopyOpenSpecification"/>.
/// </summary>
public class RemodelSeatAdapterShapeTests
{
    private static readonly Assembly AddIn = typeof(SwRemodelBridgeSeat).Assembly;

    private const string SeatNamespace = "SwReview.AddIn.Remodel.Seat";

    /// <summary>Each adapter class, the interfaces it is named for, and what it is built from.</summary>
    public static IEnumerable<object[]> Adapters() => new[]
    {
        new object[]
        {
            typeof(SwScopeSignalReader), new[] { typeof(IScopeSignalSource) }, new[] { typeof(IModelDoc2) },
        },
        new object[]
        {
            typeof(SwRemodelCopyDocument),
            new[] { typeof(IRemodelDocument), typeof(IRemodelCopyTarget), typeof(IRemodelTarget), typeof(IScopeSignalSource), typeof(IGeometrySource) },
            new[] { typeof(ISldWorks), typeof(IModelDoc2) },
        },
        new object[]
        {
            typeof(SwRemodelProbeSource), new[] { typeof(IRemodelProbeSource), typeof(IScopeSignalSource) }, new[] { typeof(ISldWorks) },
        },
        new object[]
        {
            typeof(SwRemodelBridgeSeat), new[] { typeof(ExtractorSeat), typeof(IRemodelToggleHost) }, new[] { typeof(ISldWorks) },
        },
    };

    public static IEnumerable<object[]> AdapterTypes() => Adapters().Select(row => new[] { row[0] });

    /// <summary>Every type in the seat's folder, the static helpers included.</summary>
    public static IEnumerable<object[]> SeatTypes() =>
        AddIn.GetTypes()
            .Where(type => type.Namespace == SeatNamespace && !IsCompilerGenerated(type))
            .Select(type => new object[] { type });

    // ---- 1. exactly the interfaces each is named for ------------------------------------------------

    [Theory]
    [MemberData(nameof(Adapters))]
    public void EachAdapterIsPublicSealedAndImplementsExactlyItsInterfaces(Type adapter, Type[] named, Type[] builtFrom)
    {
        Assert.NotNull(builtFrom);
        Assert.True(adapter.IsPublic, $"{adapter.Name} is not public; ToolServiceHost.Attach builds the seat.");
        Assert.True(adapter.IsSealed, $"{adapter.Name} is not sealed.");
        Assert.Equal(
            named.Select(type => type.FullName).OrderBy(name => name, StringComparer.Ordinal),
            adapter.GetInterfaces().Select(type => type.FullName).OrderBy(name => name, StringComparer.Ordinal));
    }

    [Theory]
    [MemberData(nameof(Adapters))]
    public void EachAdapterIsBuiltFromTheSolidWorksObjectsAlone(Type adapter, Type[] named, Type[] builtFrom)
    {
        Assert.NotNull(named);
        ConstructorInfo constructor = Assert.Single(
            adapter.GetConstructors(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic));

        Assert.True(constructor.IsPublic);
        Assert.Equal(builtFrom, constructor.GetParameters().Select(parameter => parameter.ParameterType));
    }

    /// <summary>Every member of an adapter's interfaces is one it answers - none is left to throw by omission.</summary>
    [Theory]
    [MemberData(nameof(Adapters))]
    public void EveryInterfaceMemberIsImplementedPublicly(Type adapter, Type[] named, Type[] builtFrom)
    {
        Assert.NotNull(builtFrom);
        foreach (Type contract in named)
        {
            InterfaceMapping map = adapter.GetInterfaceMap(contract);
            Assert.All(map.TargetMethods, method => Assert.True(method.IsPublic, $"{adapter.Name}.{method.Name} is not public."));
        }
    }

    [Fact]
    public void TheSeatFolderHoldsTheAdaptersAndTheirTwoHelpersAndNothingElse()
    {
        Assert.Equal(
            new[]
            {
                nameof(CopyOpenSpecification), nameof(SwRemodelBridgeSeat), nameof(SwRemodelCopyDocument),
                nameof(SwRemodelProbeSource), "SwRemodelReads", nameof(SwScopeSignalReader),
            },
            SeatTypes().Select(row => ((Type)row[0]).Name).OrderBy(name => name, StringComparer.Ordinal));
    }

    // ---- 2. no gate, no guard, no scope ---------------------------------------------------------------

    [Theory]
    [MemberData(nameof(SeatTypes))]
    public void NoSeatClassTakesOrHoldsAGateAGuardOrAScope(Type seatType)
    {
        Assert.Empty(AdapterShape.MentionsOfForbiddenTypes(seatType));
    }

    /// <summary>The check above is not vacuous: a class that holds a gate is what it flags.</summary>
    [Fact]
    public void TheForbiddenTypeCheckFlagsAClassThatHoldsAGate()
    {
        Assert.NotEmpty(AdapterShape.MentionsOfForbiddenTypes(typeof(GatedEquationTarget)));
    }

    /// <summary>
    /// A static reach to a gate would not show in a class's shape, so the code is read: outside its
    /// comments, no file in the seat's folder names a gate, a guard or a scope, or makes a gated call.
    /// </summary>
    [Fact]
    public void NoSeatSourceFileMakesAGatedCall()
    {
        List<string> files = SeatSourceFiles().ToList();
        Assert.Equal(6, files.Count);

        foreach (string file in files)
        {
            string code = AdapterShape.CodeOutsideComments(File.ReadAllText(file));
            foreach (string token in AdapterShape.GatedCallTokens)
            {
                Assert.False(
                    code.Contains(token),
                    $"{Path.GetFileName(file)} says '{token}' outside its comments; the bridge gates the seat from outside.");
            }
        }
    }

    // ---- 3. no document path it did not create --------------------------------------------------------

    /// <summary>
    /// The only string parameters in the seat's folder that could carry a document's path are these, each
    /// an interface member that names one - the copy the scope holds, the engineer's open source
    /// (read, never opened), the copy to open or close - or the two places that check and open the
    /// copy path such a member was handed. No constructor takes a path, and no other member does.
    /// </summary>
    [Fact]
    public void TheOnlyPathTakingMembersAreTheInterfaceMembersThatNameOne()
    {
        var allowed = new HashSet<string>(StringComparer.Ordinal)
        {
            "SwRemodelCopyDocument.GetOpenDocumentIdentity(documentPath)", // VerifyTarget's check 3, handed the copy path
            "SwRemodelProbeSource.IsOpen(documentPath)",                   // the engineer's open source, never opened
            "SwRemodelBridgeSeat.OpenDocument(documentPath)",              // the copy, refused unless inside copy/
            "SwRemodelBridgeSeat.CloseDocument(documentPath)",             // the tagged copy, refused unless inside copy/
            "SwRemodelBridgeSeat.GetVault(sourcePath)",                    // answers null and reads nothing
            "SwRemodelBridgeSeat.RequireCopyPath(documentPath)",           // the copy check itself
            "CopyOpenSpecification.For(copyPath)",                         // the path OpenDocument has checked
        };

        List<string> found = SeatTypes()
            .Select(row => (Type)row[0])
            .SelectMany(type => AdapterShape.DeclaredParameters(type).Select(declared => (type, declared.Member, declared.Parameter)))
            .Where(item => IsPathLike(item.Parameter))
            .Select(item => $"{item.type.Name}.{item.Member.Name}({item.Parameter.Name})")
            .OrderBy(name => name, StringComparer.Ordinal)
            .ToList();

        Assert.Equal(allowed.OrderBy(name => name, StringComparer.Ordinal), found);
    }

    /// <summary>Every path-taking public member is an interface member that takes that path.</summary>
    [Fact]
    public void EachPublicPathTakingMemberImplementsAnInterfaceMemberThatNamesThePath()
    {
        foreach (object[] row in Adapters())
        {
            var adapter = (Type)row[0];
            var named = (Type[])row[1];
            var implementations = new HashSet<MethodInfo>(named.SelectMany(contract => adapter.GetInterfaceMap(contract).TargetMethods));

            foreach (MethodInfo method in adapter.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.DeclaredOnly))
            {
                if (method.GetParameters().Any(IsPathLike))
                {
                    Assert.True(implementations.Contains(method), $"{adapter.Name}.{method.Name} takes a path and is no interface member.");
                }
            }
        }
    }

    /// <summary>No seat class holds a string: a path it could keep is a path it could reuse.</summary>
    [Theory]
    [MemberData(nameof(SeatTypes))]
    public void NoSeatClassHoldsAString(Type seatType)
    {
        Assert.Empty(AdapterShape.AllFields(seatType).Where(field => !field.IsLiteral && field.FieldType == typeof(string)).Select(field => field.Name));
    }

    // ---- written once ---------------------------------------------------------------------------------

    /// <summary>
    /// The equation manager and the mass property are lane A's shared, ungated classes: no class in
    /// the add-in maps either interface itself, and the copy's adapter builds each shared class.
    /// </summary>
    [Fact]
    public void TheCopyUsesLaneAsSharedEquationAndMassPropertyClasses()
    {
        Assert.DoesNotContain(AddIn.GetTypes(), type => typeof(IEquationTarget).IsAssignableFrom(type) || typeof(IMassPropertyReading).IsAssignableFrom(type));

        string code = AdapterShape.CodeOutsideComments(SeatSource("SwRemodelCopyDocument.cs"));
        Assert.Matches(@"new\s+SwEquationManager\s*\(", code);
        Assert.Matches(@"new\s+SwMassProperty\s*\(", code);
    }

    /// <summary>The seat's four toggle members delegate to the one mapping, and it names no toggle member of its own.</summary>
    [Fact]
    public void TheSeatDelegatesItsFourToggleMembers()
    {
        string code = AdapterShape.CodeOutsideComments(SeatSource("SwRemodelBridgeSeat.cs"));

        Assert.Single(Regex.Matches(code, @"new\s+SwRemodelToggleHost\s*\(\s*swApp\s*\)").Cast<Match>());
        Assert.Matches(@"GetUserPreferenceToggle\(int toggle\)\s*=>\s*_toggles\.GetUserPreferenceToggle\(toggle\);", code);
        Assert.Matches(@"SetUserPreferenceToggle\(int toggle, bool value\)\s*=>\s*_toggles\.SetUserPreferenceToggle\(toggle, value\);", code);
        Assert.Matches(@"GetCommandInProgress\(\)\s*=>\s*_toggles\.GetCommandInProgress\(\);", code);
        Assert.Matches(@"SetCommandInProgress\(bool value\)\s*=>\s*_toggles\.SetCommandInProgress\(value\);", code);
        Assert.DoesNotMatch(@"_swApp\s*\.\s*(GetUserPreferenceToggle|SetUserPreferenceToggle|CommandInProgress)\b", code);
    }

    /// <summary>
    /// The copy's adapter and the probe source read the scope signals through the one shared reader:
    /// each builds it, and neither makes a signal call of its own.
    /// </summary>
    [Theory]
    [InlineData("SwRemodelCopyDocument.cs")]
    [InlineData("SwRemodelProbeSource.cs")]
    public void TheSignalsAreReadThroughTheSharedReader(string file)
    {
        string code = AdapterShape.CodeOutsideComments(SeatSource(file));

        Assert.Matches(@"new\s+SwScopeSignalReader\s*\(\s*document\s*\)", code);

        // A signal's interop call on any receiver but the shared reader. The copy's own
        // IGeometrySource.GetBodies reads GetBodies2 too - the bodies the mass property is taken
        // over - so that one call is the copy's.
        var signalCall = new Regex(
            @"(?<!_signals|Signals\(\))\s*\.\s*(GetBodies2|IsWeldment|GetSheetMetalFolder|IsMeshBody|IsGraphicsBody|"
                + @"Is3DInterconnectFeature|GetImportedFileName|GetConfigurationNames|GetSpecificFeature2|GetFeatures)\b",
            RegexOptions.CultureInvariant);
        List<string> own = signalCall.Matches(code).Cast<Match>().Select(match => match.Groups[1].Value).ToList();
        if (file == "SwRemodelCopyDocument.cs")
        {
            Assert.Equal(new[] { "GetBodies2" }, own);
        }
        else
        {
            Assert.Empty(own);
        }
    }

    /// <summary>
    /// Both opens of a copy state the specification's flags in one place: in the add-in, only
    /// <see cref="CopyOpenSpecification"/> sets them, and the pane's own open goes through it.
    /// </summary>
    [Fact]
    public void OnlyTheOpenSpecificationHelperSetsTheOpenFlags()
    {
        string addIn = Path.Combine(ErrorLabelsCoverTheHostTests.RepositoryRoot(), "extractor", "SwReview.AddIn");
        var assignment = new Regex(@"\.\s*(Silent|LoadModel|ReadOnly|ViewOnly)\s*=[^=]", RegexOptions.CultureInvariant);

        List<string> setters = ProductFiles(addIn)
            .Where(file => assignment.IsMatch(AdapterShape.CodeOutsideComments(File.ReadAllText(file))))
            .Select(Path.GetFileName)
            .ToList();

        Assert.Equal(new[] { "CopyOpenSpecification.cs" }, setters);
        Assert.Contains(
            "CopyOpenSpecification.For(_swApp, copyPath)",
            File.ReadAllText(Path.Combine(addIn, "Remodel", "SwRemodelSeat.cs")),
            StringComparison.Ordinal);
    }

    /// <summary>The add-in's own seat and the bridge seat stay apart: different names, different interfaces.</summary>
    [Fact]
    public void TheTwoSeatsAreNamedApart()
    {
        Assert.NotEqual(typeof(SwRemodelSeat).Name, typeof(SwRemodelBridgeSeat).Name);
        Assert.Equal(new[] { typeof(SwReview.AddIn.Remodel.IRemodelSeat) }, typeof(SwRemodelSeat).GetInterfaces());
        Assert.DoesNotContain(typeof(SwReview.AddIn.Remodel.IRemodelSeat), typeof(SwRemodelBridgeSeat).GetInterfaces());
    }

    // ---- helpers --------------------------------------------------------------------------------------

    private static string SeatFolder() =>
        Path.Combine(ErrorLabelsCoverTheHostTests.RepositoryRoot(), "extractor", "SwReview.AddIn", "Remodel", "Seat");

    private static IEnumerable<string> SeatSourceFiles() => Directory.EnumerateFiles(SeatFolder(), "*.cs", SearchOption.AllDirectories);

    private static string SeatSource(string fileName) => File.ReadAllText(Path.Combine(SeatFolder(), fileName));

    private static IEnumerable<string> ProductFiles(string root) =>
        Directory.EnumerateFiles(root, "*.cs", SearchOption.AllDirectories)
            .Where(file => !file.Split(Path.DirectorySeparatorChar).Any(part => part == "obj" || part == "bin"));

    /// <summary>A string parameter whose name could carry a document's path; a document object is not a path.</summary>
    private static bool IsPathLike(ParameterInfo parameter) =>
        parameter.ParameterType == typeof(string) && AdapterShape.PathLike.IsMatch(parameter.Name ?? string.Empty);

    private static bool IsCompilerGenerated(Type type) =>
        type.GetCustomAttributes(typeof(System.Runtime.CompilerServices.CompilerGeneratedAttribute), false).Length > 0
        || type.Name.StartsWith("<", StringComparison.Ordinal);
}
