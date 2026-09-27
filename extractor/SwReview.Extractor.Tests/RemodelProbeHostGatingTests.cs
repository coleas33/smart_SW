using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.Remoting.Messaging;
using System.Runtime.Remoting.Proxies;
using System.Text.RegularExpressions;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Sw;
using SwReview.Extractor.Tests.Fakes;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// 004 build order, lane A (T152's probe-host case; T153's amendment). The probe host's
/// equation and mass-property wrappers are split: the interop calls live once, ungated, in
/// <see cref="SwEquationManager"/> and <see cref="SwMassProperty"/>, which the copy's adapter
/// (T153) uses directly because the bridge gates it from outside; and the probe host wraps them
/// in <see cref="GatedEquationTarget"/> and <see cref="GatedMassPropertyReading"/>, because the
/// probe executors call them with no gate around them.
///
/// What must not move is what the probe records: every call still gated <b>once</b>, under the
/// bare key it has always been gated under, so every probe's gated set and ledger stay as they
/// were. The keys are pinned here by value (<see cref="ProbeWrapperCases"/>), and each key is also
/// the name of the interop member its call reaches, which the composed case checks end to end.
/// </summary>
public class RemodelProbeHostGatingTests
{
    // ---- each call gated once, under its bare key ---------------------------------------

    [Theory]
    [MemberData(nameof(ProbeWrapperCases.EquationMembers), MemberType = typeof(ProbeWrapperCases))]
    public void EachEquationCallIsGatedOnceUnderItsBareKey(string member)
    {
        (SwGate gate, GateCallLog log) = ProbeGate();
        var equations = new FakeEquationManager();

        ProbeWrapperCases.CallEquation(new GatedEquationTarget(gate, equations), member);

        Assert.Equal(new[] { ProbeWrapperCases.EquationKey(member) }, log.Keys);
        Assert.Equal(new[] { member }, equations.Members);
        Assert.Empty(log.Refusals);
    }

    [Theory]
    [MemberData(nameof(ProbeWrapperCases.MassPropertyMembers), MemberType = typeof(ProbeWrapperCases))]
    public void EachMassPropertyCallIsGatedOnceUnderItsBareKey(string member)
    {
        (SwGate gate, GateCallLog log) = ProbeGate();
        var massProperty = new FakeMassProperty();

        ProbeWrapperCases.CallMassProperty(new GatedMassPropertyReading(gate, massProperty), member);

        Assert.Equal(new[] { ProbeWrapperCases.MassPropertyKey(member) }, log.Keys);
        Assert.Equal(new[] { member }, massProperty.Members);
        Assert.Empty(log.Refusals);
    }

    /// <summary>
    /// The probe host's own composition, end to end: the gate is asked once, and the one interop
    /// member reached is the one the key names, so the gated set says what was really called.
    /// </summary>
    [Theory]
    [MemberData(nameof(ProbeWrapperCases.EquationMembers), MemberType = typeof(ProbeWrapperCases))]
    public void TheProbeHostsEquationCompositionCallsTheInteropMemberItsKeyNames(string member)
    {
        (SwGate gate, GateCallLog log) = ProbeGate();
        var interop = new InteropRecorder<IEquationMgr>();

        ProbeWrapperCases.CallEquation(new GatedEquationTarget(gate, new SwEquationManager(interop.Instance)), member);

        string key = ProbeWrapperCases.EquationKey(member);
        Assert.Equal(new[] { key }, log.Keys);
        Assert.Equal(new[] { key }, interop.Calls.Select(call => call.Member));
    }

    [Theory]
    [MemberData(nameof(ProbeWrapperCases.MassPropertyMembers), MemberType = typeof(ProbeWrapperCases))]
    public void TheProbeHostsMassPropertyCompositionCallsTheInteropMemberItsKeyNames(string member)
    {
        (SwGate gate, GateCallLog log) = ProbeGate();
        var interop = new InteropRecorder<IMassProperty2>();

        ProbeWrapperCases.CallMassProperty(new GatedMassPropertyReading(gate, new SwMassProperty(interop.Instance)), member);

        string key = ProbeWrapperCases.MassPropertyKey(member);
        Assert.Equal(new[] { key }, log.Keys);
        Assert.Equal(new[] { key }, interop.Calls.Select(call => call.Member));
    }

    /// <summary>
    /// What <c>probe-remodel.log</c> records is the probe gate's distinct gated set
    /// (<see cref="RecordingGateObserver"/>). Every member of both interfaces, called once in
    /// order through the probe's own gate, leaves exactly the bare keys - and none is refused,
    /// the writes (<c>Add3</c>, <c>set_Equation</c>, <c>Delete</c>) included.
    /// </summary>
    [Fact]
    public void TheProbeGateRecordsTheBareKeysAndRefusesNone()
    {
        var observer = new RecordingGateObserver();
        SwGate gate = SwReview.Extractor.Console.Program.RemodelProbeGate(observer);
        var equations = new GatedEquationTarget(gate, new SwEquationManager(new InteropRecorder<IEquationMgr>().Instance));
        var massProperty = new GatedMassPropertyReading(gate, new SwMassProperty(new InteropRecorder<IMassProperty2>().Instance));

        foreach ((string member, string _) in ProbeWrapperCases.Equation)
        {
            ProbeWrapperCases.CallEquation(equations, member);
        }

        foreach ((string member, string _) in ProbeWrapperCases.MassProperty)
        {
            ProbeWrapperCases.CallMassProperty(massProperty, member);
        }

        Assert.Equal(
            ProbeWrapperCases.Equation.Select(row => row.Key).Concat(ProbeWrapperCases.MassProperty.Select(row => row.Key)),
            observer.Members);
        Assert.Empty(observer.Refusals);
    }

    // ---- the wrapper adds a gate and nothing else ----------------------------------------

    [Fact]
    public void TheGatedEquationTargetPassesArgumentsAndAnswersThroughUnchanged()
    {
        SwGate gate = ProbeGate().Gate;
        var equations = new FakeEquationManager { Add3Answer = 42, Add2Answer = 43 };
        equations.Equations.AddRange(new[] { "\"w\" = 120", "\"h\" = 40" });
        var target = new GatedEquationTarget(gate, equations);

        Assert.Equal(2, target.GetCount());
        Assert.Equal("\"h\" = 40", target.GetEquation(1));
        Assert.Equal(42, target.Add3(1, "\"d\" = 5", true, 1, ProbeWrapperCases.ConfigNames));
        Assert.Equal(new[] { "\"w\" = 120", "\"d\" = 5", "\"h\" = 40" }, equations.Equations);
        Assert.Equal(43, target.Add2(-1, "\"e\" = 6", true));
        target.SetEquation(0, "\"w\" = 121");
        Assert.Equal(0, target.SetEquationAndConfigurationOption(1, "\"d\" = 7", 2, null));
        Assert.Equal(0, target.Delete(2));

        Assert.Equal(new[] { "\"w\" = 121", "\"d\" = 7", "\"e\" = 6" }, equations.Equations);
    }

    /// <summary>An unreadable equation stays null through the wrapper; it is never an empty string.</summary>
    [Fact]
    public void AnUnreadableEquationStaysNullThroughTheGatedWrapper()
    {
        SwGate gate = ProbeGate().Gate;
        var equations = new FakeEquationManager { EquationUnreadable = true };
        equations.Equations.Add("\"w\" = 120");

        Assert.Null(new GatedEquationTarget(gate, equations).GetEquation(0));
    }

    [Fact]
    public void TheGatedMassPropertyReadingPassesArgumentsAndAnswersThroughUnchanged()
    {
        SwGate gate = ProbeGate().Gate;
        var massProperty = new FakeMassProperty
        {
            RecalculateAnswer = false,
            Volume = 0.5,
            SurfaceArea = 0.25,
            Mass = 1.5,
            Density = 7850.0,
            CenterOfMass = null,
            PrincipalMoments = new[] { 3.0, 1.0, 2.0 },
        };
        var target = new GatedMassPropertyReading(gate, massProperty);
        var bodies = new List<object> { new object() };

        target.SetAccuracyLevel(RemodelGeometry.HigherAccuracy);
        target.SetSelectedItems(bodies);
        target.SetUseSystemUnits(true);

        Assert.Equal(RemodelGeometry.HigherAccuracy, massProperty.AccuracyLevel);
        Assert.Same(bodies, massProperty.SelectedItems);
        Assert.True(massProperty.UseSystemUnits);
        Assert.False(target.Recalculate());
        Assert.Equal(0.5, target.GetVolume());
        Assert.Equal(0.25, target.GetSurfaceArea());
        Assert.Equal(1.5, target.GetMass());
        Assert.Equal(7850.0, target.GetDensity());
        Assert.Null(target.GetCenterOfMass());

        // Unsorted: sorting the moments is RemodelGeometry's rule, not the wrapper's.
        Assert.Equal(new[] { 3.0, 1.0, 2.0 }, target.GetPrincipalMomentsOfInertia());
    }

    [Fact]
    public void TheGatedWrappersRefuseAMissingGateOrAMissingInner()
    {
        SwGate gate = ProbeGate().Gate;

        Assert.Equal("gate", Assert.Throws<ArgumentNullException>(() => new GatedEquationTarget(null!, new FakeEquationManager())).ParamName);
        Assert.Equal("equations", Assert.Throws<ArgumentNullException>(() => new GatedEquationTarget(gate, null!)).ParamName);
        Assert.Equal("gate", Assert.Throws<ArgumentNullException>(() => new GatedMassPropertyReading(null!, new FakeMassProperty())).ParamName);
        Assert.Equal("massProperty", Assert.Throws<ArgumentNullException>(() => new GatedMassPropertyReading(gate, null!)).ParamName);
    }

    // ---- once means once: the breaker and the guard ---------------------------------------

    /// <summary>
    /// A sick session is counted once per call: a wrapper that gated twice would open the circuit
    /// on half the failures it should take.
    /// </summary>
    [Fact]
    public void AFailingEquationCallIsCountedOnceByTheBreaker()
    {
        (SwGate gate, GateCallLog log) = ProbeGate();
        var interop = new InteropRecorder<IEquationMgr>().Fail("GetCount", new COMException("The session went away."));
        var target = new GatedEquationTarget(gate, new SwEquationManager(interop.Instance));

        Assert.Throws<COMException>(() => target.GetCount());

        Assert.Equal(1, gate.Breaker.ConsecutiveFailures);
        Assert.Equal(new[] { "GetCount" }, log.Keys);
    }

    [Fact]
    public void AFailingMassPropertyCallIsCountedOnceByTheBreaker()
    {
        (SwGate gate, GateCallLog log) = ProbeGate();
        var interop = new InteropRecorder<IMassProperty2>().Fail("get_Volume", new COMException("The session went away."));
        var target = new GatedMassPropertyReading(gate, new SwMassProperty(interop.Instance));

        Assert.Throws<COMException>(() => target.GetVolume());

        Assert.Equal(1, gate.Breaker.ConsecutiveFailures);
        Assert.Equal(new[] { "get_Volume" }, log.Keys);
    }

    /// <summary>The guard judges before the call: a refused key never reaches SOLIDWORKS.</summary>
    [Theory]
    [MemberData(nameof(ProbeWrapperCases.EquationMembers), MemberType = typeof(ProbeWrapperCases))]
    public void ARefusedEquationKeyNeverReachesTheInteropObject(string member)
    {
        var log = new GateCallLog();
        var gate = new SwGate(new CircuitBreaker(), new RefuseEverything()) { Observer = log };
        var interop = new InteropRecorder<IEquationMgr>();

        Assert.Throws<MutatingCallError>(
            () => ProbeWrapperCases.CallEquation(new GatedEquationTarget(gate, new SwEquationManager(interop.Instance)), member));

        string key = ProbeWrapperCases.EquationKey(member);
        Assert.Empty(interop.Calls);
        Assert.Equal(new[] { key }, log.Keys);
        Assert.Equal(key, Assert.Single(log.Refusals).MemberName);
    }

    [Theory]
    [MemberData(nameof(ProbeWrapperCases.MassPropertyMembers), MemberType = typeof(ProbeWrapperCases))]
    public void ARefusedMassPropertyKeyNeverReachesTheInteropObject(string member)
    {
        var log = new GateCallLog();
        var gate = new SwGate(new CircuitBreaker(), new RefuseEverything()) { Observer = log };
        var interop = new InteropRecorder<IMassProperty2>();

        Assert.Throws<MutatingCallError>(
            () => ProbeWrapperCases.CallMassProperty(new GatedMassPropertyReading(gate, new SwMassProperty(interop.Instance)), member));

        string key = ProbeWrapperCases.MassPropertyKey(member);
        Assert.Empty(interop.Calls);
        Assert.Equal(new[] { key }, log.Keys);
        Assert.Equal(key, Assert.Single(log.Refusals).MemberName);
    }

    // ---- the probe host itself (a source read: it cannot run without a seat) -------------

    /// <summary>The old gated classes are gone, so nothing can reach the interop through a second mapping.</summary>
    [Fact]
    public void TheProbeHostsOwnGatedInteropClassesAreGone()
    {
        Assembly extractor = typeof(SwRemodelProbeHost).Assembly;

        Assert.Null(extractor.GetType("SwReview.Extractor.Rms.SwEquationTarget"));
        Assert.Null(extractor.GetType("SwReview.Extractor.Rms.SwMassPropertyReading"));
    }

    /// <summary>
    /// Every equation manager and mass property the probe host builds is the shared class inside
    /// the probe gate's wrapper - never the shared class bare, which would be an ungated call from
    /// a caller with no gate around it.
    /// </summary>
    [Theory]
    [InlineData("SwEquationManager", "GatedEquationTarget")]
    [InlineData("SwMassProperty", "GatedMassPropertyReading")]
    public void TheProbeHostBuildsEachSharedClassOnlyInsideItsGatedWrapper(string shared, string wrapper)
    {
        string source = ProbeWrapperCases.ProductSource("SwRemodelProbeHost.cs");

        int built = Regex.Matches(source, @"new\s+" + shared + @"\s*\(").Count;
        int wrapped = Regex.Matches(source, @"new\s+" + wrapper + @"\s*\(\s*_gate\s*,\s*new\s+" + shared + @"\s*\(").Count;

        Assert.True(built >= 1, $"SwRemodelProbeHost.cs builds no {shared}.");
        Assert.Equal(built, wrapped);
    }

    /// <summary>
    /// The split's point: the probe host gates none of the two interfaces' members itself, so each
    /// interop mapping is written once, in the shared class, and each key is gated in one place.
    /// </summary>
    [Fact]
    public void TheProbeHostGatesNoEquationOrMassPropertyMemberItself()
    {
        string source = ProbeWrapperCases.ProductSource("SwRemodelProbeHost.cs");
        var wrapperKeys = new HashSet<string>(StringComparer.Ordinal)
        {
            "EquationGetCount", "EquationGetEquationText", "AddEquation", "EquationAdd2", "EquationSetEquation",
            "EquationSetEquationAndConfigurationOption", "EquationDelete",
            "MassPropertySetAccuracyLevel", "MassPropertySetSelectedItems", "MassPropertySetUseSystemUnits",
            "MassPropertyRecalculate", "MassPropertyGetVolume", "MassPropertyGetSurfaceArea", "MassPropertyGetCenterOfMass",
            "MassPropertyGetPrincipalMoments", "MassPropertyGetMass", "MassPropertyGetDensity",
        };

        List<string> gatedHere = Regex.Matches(source, @"_gate\s*\.\s*Call\s*\(\s*Member\.(\w+)")
            .Cast<Match>()
            .Select(match => match.Groups[1].Value)
            .ToList();

        Assert.Contains("GetEquationMgr", gatedHere);
        Assert.DoesNotContain(gatedHere, wrapperKeys.Contains);
    }

    private static (SwGate Gate, GateCallLog Log) ProbeGate()
    {
        // The probe's own gate (its guard and its breaker), with an observer that counts.
        SwGate gate = SwReview.Extractor.Console.Program.RemodelProbeGate(new RecordingGateObserver());
        var log = new GateCallLog();
        gate.Observer = log;
        return (gate, log);
    }

    private sealed class RefuseEverything : ICallGuard
    {
        public void Assert(string interopMemberName) =>
            throw new MutatingCallError(interopMemberName, $"{interopMemberName} is refused by the test guard.");
    }
}

/// <summary>
/// 004 build order, lane A (T152's reflection case for T153's two shared classes; T153's
/// amendment). <see cref="SwEquationManager"/> and <see cref="SwMassProperty"/> are the one
/// mapping of <see cref="IEquationTarget"/> onto <c>IEquationMgr</c> and of
/// <see cref="IMassPropertyReading"/> onto <c>IMassProperty2</c>: one interop member per interface
/// member, public, and <b>ungated</b> - they take and hold no <see cref="SwGate"/>, no
/// <see cref="ICallGuard"/> and no <see cref="RemodelScope"/>, because the bridge gates the
/// copy's adapter from outside and a gate inside would gate each call twice.
/// </summary>
public class SharedRemodelInteropTests
{
    private static readonly Type[] Forbidden = { typeof(SwGate), typeof(ICallGuard), typeof(RemodelScope) };

    /// <summary>Each shared class, the interface it is named for, and the interop object it maps that interface onto.</summary>
    public static IEnumerable<object[]> SharedClasses() => new[]
    {
        new object[] { typeof(SwEquationManager), typeof(IEquationTarget), typeof(IEquationMgr) },
        new object[] { typeof(SwMassProperty), typeof(IMassPropertyReading), typeof(IMassProperty2) },
    };

    public static IEnumerable<object[]> SharedClassAndInterface() => SharedClasses().Select(row => new[] { row[0], row[1] });

    public static IEnumerable<object[]> SharedClassAndInterop() => SharedClasses().Select(row => new[] { row[0], row[2] });

    public static IEnumerable<object[]> SharedClass() => SharedClasses().Select(row => new[] { row[0] });

    // ---- the shape (reflection) -----------------------------------------------------------

    [Theory]
    [MemberData(nameof(SharedClassAndInterface))]
    public void TheSharedClassIsPublicSealedAndImplementsExactlyItsInterface(Type shared, Type named)
    {
        Assert.True(shared.IsPublic, $"{shared.Name} is not public; the copy's adapter in the add-in uses it.");
        Assert.True(shared.IsSealed, $"{shared.Name} is not sealed.");
        Assert.Equal(new[] { named }, shared.GetInterfaces());
    }

    [Theory]
    [MemberData(nameof(SharedClassAndInterop))]
    public void TheSharedClassIsBuiltFromItsInteropObjectAlone(Type shared, Type interop)
    {
        ConstructorInfo constructor = Assert.Single(
            shared.GetConstructors(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic));

        Assert.True(constructor.IsPublic);
        Assert.Equal(new[] { interop }, constructor.GetParameters().Select(parameter => parameter.ParameterType));
    }

    /// <summary>The heart of T153's amendment: the bridge gates; the shared class never does.</summary>
    [Theory]
    [MemberData(nameof(SharedClass))]
    public void TheSharedClassTakesAndHoldsNoGateNoGuardAndNoScope(Type shared)
    {
        Assert.Empty(MentionsOfForbiddenTypes(shared));
    }

    /// <summary>
    /// The check above is not vacuous: the probe host's gated wrappers, which do hold a gate, are
    /// what it flags.
    /// </summary>
    [Theory]
    [InlineData(typeof(GatedEquationTarget))]
    [InlineData(typeof(GatedMassPropertyReading))]
    public void TheForbiddenTypeCheckFlagsAClassThatHoldsAGate(Type gated)
    {
        Assert.NotEmpty(MentionsOfForbiddenTypes(gated));
    }

    /// <summary>
    /// T152: nothing on the shared class could take a document path it did not create. Neither
    /// takes a string that names a document at all: the equation text is data.
    /// </summary>
    [Theory]
    [MemberData(nameof(SharedClass))]
    public void NoMemberOfTheSharedClassTakesADocumentPath(Type shared)
    {
        var pathLike = new Regex("path|file|document|title", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
        IEnumerable<ParameterInfo> parameters = shared
            .GetMethods(BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly)
            .Cast<MethodBase>()
            .Concat(shared.GetConstructors(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
            .SelectMany(method => method.GetParameters());

        Assert.Empty(parameters.Where(parameter => pathLike.IsMatch(parameter.Name ?? string.Empty)).Select(parameter => parameter.Name));
    }

    /// <summary>
    /// Each interop mapping is written once: of every class in the extractor that implements the
    /// interface, exactly one holds the interop object - the shared class.
    /// </summary>
    [Theory]
    [MemberData(nameof(SharedClasses))]
    public void ExactlyOneExtractorClassMapsTheInterfaceOntoItsInteropObject(Type shared, Type named, Type interop)
    {
        List<string> mappings = LoadableTypes(shared.Assembly)
            .Where(type => type.IsClass && named.IsAssignableFrom(type))
            .Where(type => AllFields(type).Any(field => field.FieldType.Assembly == interop.Assembly))
            .Select(type => type.FullName!)
            .ToList();

        Assert.Equal(new[] { shared.FullName }, mappings);
    }

    /// <summary>
    /// A static reach to a gate would not show in the class's shape, so the code itself is read:
    /// outside its comments, the shared class names no gate, no guard and no scope, and makes no
    /// gated call.
    /// </summary>
    [Theory]
    [MemberData(nameof(SharedClasses))]
    public void TheSharedClassSourceMakesNoGatedCall(Type shared, Type named, Type interop)
    {
        string code = string.Join(
            "\n",
            ProbeWrapperCases.ProductSource(shared.Name + ".cs")
                .Split('\n')
                .Where(line => !line.TrimStart().StartsWith("//", StringComparison.Ordinal)));

        foreach (string token in new[] { "SwGate", "ICallGuard", "RemodelScope", "RemodelGuard", ".Call(", ".CallOptional(", ".Assert(" })
        {
            Assert.DoesNotContain(token, code, StringComparison.Ordinal);
        }

        Assert.Contains(interop.Name, code, StringComparison.Ordinal);
        Assert.Contains(named.Name, code, StringComparison.Ordinal);
    }

    // ---- the mapping: one interop member per interface member -------------------------------

    [Theory]
    [MemberData(nameof(ProbeWrapperCases.EquationMembers), MemberType = typeof(ProbeWrapperCases))]
    public void EachEquationMemberCallsExactlyItsOneInteropMemberWithTheSameArguments(string member)
    {
        var interop = new InteropRecorder<IEquationMgr>();

        ProbeWrapperCases.CallEquation(new SwEquationManager(interop.Instance), member);

        (string called, object?[] arguments) = Assert.Single(interop.Calls);
        Assert.Equal(ProbeWrapperCases.EquationKey(member), called);
        Assert.Equal(ProbeWrapperCases.EquationArguments(member), arguments);
    }

    [Theory]
    [MemberData(nameof(ProbeWrapperCases.MassPropertyMembers), MemberType = typeof(ProbeWrapperCases))]
    public void EachMassPropertyMemberCallsExactlyItsOneInteropMemberWithTheSameArguments(string member)
    {
        var interop = new InteropRecorder<IMassProperty2>();

        ProbeWrapperCases.CallMassProperty(new SwMassProperty(interop.Instance), member);

        (string called, object?[] arguments) = Assert.Single(interop.Calls);
        Assert.Equal(ProbeWrapperCases.MassPropertyKey(member), called);
        Assert.Equal(ProbeWrapperCases.MassPropertyArguments(member), arguments);
    }

    [Fact]
    public void EachEquationAnswerIsTheInteropMembersAnswer()
    {
        var interop = new InteropRecorder<IEquationMgr>()
            .Answer("GetCount", 7)
            .Answer("get_Equation", "\"w\" = 120")
            .Answer("Add3", 11)
            .Answer("Add2", 12)
            .Answer("SetEquationAndConfigurationOption", 13)
            .Answer("Delete", 14);
        var equations = new SwEquationManager(interop.Instance);

        Assert.Equal(7, equations.GetCount());
        Assert.Equal("\"w\" = 120", equations.GetEquation(0));
        Assert.Equal(11, equations.Add3(-1, "\"a\" = 1", true, 1, null));
        Assert.Equal(12, equations.Add2(-1, "\"a\" = 1", true));
        Assert.Equal(13, equations.SetEquationAndConfigurationOption(0, "\"a\" = 2", 1, null));
        Assert.Equal(14, equations.Delete(0));
    }

    /// <summary><c>get_Equation</c>'s null is unreadable and stays null; it never becomes <c>""</c>.</summary>
    [Fact]
    public void AnUnreadableEquationStaysNull()
    {
        var interop = new InteropRecorder<IEquationMgr>().Answer("get_Equation", null);

        Assert.Null(new SwEquationManager(interop.Instance).GetEquation(3));
    }

    [Fact]
    public void EachMassPropertyAnswerIsTheInteropMembersAnswer()
    {
        var interop = new InteropRecorder<IMassProperty2>()
            .Answer("Recalculate", true)
            .Answer("get_Volume", 0.5)
            .Answer("get_SurfaceArea", 0.25)
            .Answer("get_Mass", 1.5)
            .Answer("get_Density", 7850.0);
        var massProperty = new SwMassProperty(interop.Instance);

        Assert.True(massProperty.Recalculate());
        Assert.Equal(0.5, massProperty.GetVolume());
        Assert.Equal(0.25, massProperty.GetSurfaceArea());
        Assert.Equal(1.5, massProperty.GetMass());
        Assert.Equal(7850.0, massProperty.GetDensity());
    }

    /// <summary>
    /// The bodies are handed to SOLIDWORKS as a fresh <c>object[]</c> in the caller's order: the
    /// interop setter takes a SAFEARRAY, never the caller's own list.
    /// </summary>
    [Fact]
    public void TheSelectedBodiesAreHandedOverAsAFreshArrayInOrder()
    {
        var interop = new InteropRecorder<IMassProperty2>();
        var bodies = new List<object> { new object(), new object(), new object() };

        new SwMassProperty(interop.Instance).SetSelectedItems(bodies);

        object handed = Assert.Single(Assert.Single(interop.Calls).Arguments)!;
        object[] array = Assert.IsType<object[]>(handed);
        Assert.Equal(bodies, array);
        Assert.NotSame(bodies, handed);
    }

    [Fact]
    public void MissingBodiesAreRefusedBeforeSolidWorksIsAsked()
    {
        var interop = new InteropRecorder<IMassProperty2>();

        Assert.Equal(
            "bodies",
            Assert.Throws<ArgumentNullException>(() => new SwMassProperty(interop.Instance).SetSelectedItems(null!)).ParamName);
        Assert.Empty(interop.Calls);
    }

    [Fact]
    public void TheSharedClassesRefuseAMissingInteropObject()
    {
        Assert.Equal("manager", Assert.Throws<ArgumentNullException>(() => new SwEquationManager(null!)).ParamName);
        Assert.Equal("massProperty", Assert.Throws<ArgumentNullException>(() => new SwMassProperty(null!)).ParamName);
    }

    // ---- a triple is read only from a one-dimensional array of numbers ----------------------

    /// <summary>
    /// What <c>get_CenterOfMass</c> and <c>get_PrincipalMomentsOfInertia</c> may answer, and what
    /// is read from it. A SAFEARRAY of doubles usually arrives as a <c>double[]</c>; anything else
    /// is converted only when every element is a number, and is otherwise unreadable (null) - never
    /// a zero for a null element and never a culture-dependent parse of a string, because a
    /// guessed number is one the geometry gate would compare (<see cref="RemodelGeometry"/>).
    /// </summary>
    private static readonly IReadOnlyDictionary<string, (object? Answer, double[]? Read)> TripleShapes =
        new Dictionary<string, (object?, double[]?)>(StringComparer.Ordinal)
        {
            ["a double[] is read as it is"] = (new[] { 0.01, 0.02, 0.03 }, new[] { 0.01, 0.02, 0.03 }),
            ["an object[] of doubles is converted"] = (new object[] { 0.01, 0.02, 0.03 }, new[] { 0.01, 0.02, 0.03 }),
            ["an object[] of mixed numbers is converted"] = (
                new object[] { 1, 2.5f, 3L, 4.25m, (short)5, (byte)6, 7u, 8UL, (ushort)9, (sbyte)10 },
                new[] { 1.0, 2.5, 3.0, 4.25, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0 }),
            ["a float[] is converted"] = (new[] { 1.5f, 2.5f, 3.5f }, new[] { 1.5, 2.5, 3.5 }),
            ["an array whose lower bound is one is read from its lower bound"] = (OneBased(0.1, 0.2, 0.3), new[] { 0.1, 0.2, 0.3 }),
            ["an empty array is an empty reading"] = (new double[0], new double[0]),
            ["a wrong length is read as it is, for the caller to refuse"] = (new[] { 0.01, 0.02 }, new[] { 0.01, 0.02 }),
            ["null is unreadable"] = (null, null),
            ["a lone number is unreadable"] = (0.5, null),
            ["a string is unreadable"] = ("0.01,0.02,0.03", null),
            ["a two-dimensional array is unreadable"] = (new double[,] { { 0.01, 0.02, 0.03 } }, null),
            ["a null element makes the reading unreadable, never a zero"] = (new object?[] { 0.01, null, 0.03 }, null),
            ["a string element makes the reading unreadable, never a parse"] = (new object[] { 0.01, "0.02", 0.03 }, null),
            ["a Boolean element makes the reading unreadable"] = (new object[] { 0.01, true, 0.03 }, null),
            ["a character element makes the reading unreadable"] = (new object[] { 0.01, 'x', 0.03 }, null),
            ["an object element makes the reading unreadable"] = (new object[] { 0.01, new object(), 0.03 }, null),
        };

    public static IEnumerable<object[]> TripleCases() =>
        TripleShapes.Keys.SelectMany(shape => new[]
        {
            new object[] { shape, nameof(IMassPropertyReading.GetCenterOfMass) },
            new object[] { shape, nameof(IMassPropertyReading.GetPrincipalMomentsOfInertia) },
        });

    [Theory]
    [MemberData(nameof(TripleCases))]
    public void ATripleIsReadOnlyFromAOneDimensionalArrayOfNumbers(string shape, string member)
    {
        (object? answer, double[]? read) = TripleShapes[shape];
        var interop = new InteropRecorder<IMassProperty2>().Answer(ProbeWrapperCases.MassPropertyKey(member), answer);

        object? reading = ProbeWrapperCases.CallMassProperty(new SwMassProperty(interop.Instance), member);

        if (read == null)
        {
            Assert.Null(reading);
        }
        else
        {
            Assert.Equal(read, Assert.IsAssignableFrom<IReadOnlyList<double>>(reading));
        }
    }

    // ---- helpers -----------------------------------------------------------------------------

    private static Array OneBased(params double[] values)
    {
        Array array = Array.CreateInstance(typeof(double), new[] { values.Length }, new[] { 1 });
        for (int index = 0; index < values.Length; index++)
        {
            array.SetValue(values[index], index + 1);
        }

        return array;
    }

    /// <summary>Every place <paramref name="type"/> could take or hold a forbidden type, named.</summary>
    private static List<string> MentionsOfForbiddenTypes(Type type)
    {
        const BindingFlags Everything =
            BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
        var found = new List<string>();

        for (Type? current = type; current != null && current != typeof(object); current = current.BaseType)
        {
            found.AddRange(current.GetFields(Everything).Where(field => Mentions(field.FieldType)).Select(field => "field " + field.Name));
            found.AddRange(current.GetProperties(Everything).Where(property => Mentions(property.PropertyType)).Select(property => "property " + property.Name));

            IEnumerable<MethodBase> methods = current.GetMethods(Everything).Cast<MethodBase>().Concat(current.GetConstructors(Everything));
            foreach (MethodBase method in methods)
            {
                found.AddRange(method.GetParameters().Where(parameter => Mentions(parameter.ParameterType)).Select(parameter => $"{method.Name}({parameter.Name})"));
                if (method is MethodInfo info && Mentions(info.ReturnType))
                {
                    found.Add(method.Name + " returns " + info.ReturnType.Name);
                }
            }
        }

        return found;
    }

    /// <summary>A forbidden type, or one built from it: an array, a by-ref, or a generic argument (a <c>Func&lt;SwGate&gt;</c>).</summary>
    private static bool Mentions(Type type)
    {
        if (type.HasElementType)
        {
            return Mentions(type.GetElementType()!);
        }

        if (type.IsGenericType && type.GetGenericArguments().Any(Mentions))
        {
            return true;
        }

        return Forbidden.Any(forbidden => forbidden.IsAssignableFrom(type));
    }

    private static IEnumerable<FieldInfo> AllFields(Type type)
    {
        const BindingFlags Everything =
            BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
        for (Type? current = type; current != null && current != typeof(object); current = current.BaseType)
        {
            foreach (FieldInfo field in current.GetFields(Everything))
            {
                yield return field;
            }
        }
    }

    private static IEnumerable<Type> LoadableTypes(Assembly assembly)
    {
        try
        {
            return assembly.GetTypes();
        }
        catch (ReflectionTypeLoadException failure)
        {
            throw new InvalidOperationException(
                "The extractor's types could not all be loaded: "
                    + string.Join("; ", failure.LoaderExceptions.Select(exception => exception?.Message)),
                failure);
        }
    }
}

/// <summary>
/// The member tables and the calls both lane A suites share: every member of
/// <see cref="IEquationTarget"/> and <see cref="IMassPropertyReading"/>, the bare key the probe
/// host gates it under, and one call of it with fixed arguments.
///
/// The keys are literals on purpose: they are today's keys (<c>SwRemodelProbeHost.Member</c>)
/// pinned by value, so a constant respelt is a red test rather than a quiet change to every
/// probe's gated set. Each key is also the name the interop declares the member it reaches under,
/// which is why one table serves the gate and the mapping.
/// </summary>
internal static class ProbeWrapperCases
{
    public const string AddedText = "\"a\" = 1";

    public const string EditedText = "\"b\" = 2";

    public static readonly string[] ConfigNames = { "Default" };

    public static readonly object[] Bodies = { new object(), new object() };

    /// <summary>In interface order, which is the order the gated-set case calls them in.</summary>
    public static readonly IReadOnlyList<(string Member, string Key)> Equation = new[]
    {
        (nameof(IEquationTarget.GetCount), "GetCount"),
        (nameof(IEquationTarget.GetEquation), "get_Equation"),
        (nameof(IEquationTarget.Add3), "Add3"),
        (nameof(IEquationTarget.Add2), "Add2"),
        (nameof(IEquationTarget.SetEquation), "set_Equation"),
        (nameof(IEquationTarget.SetEquationAndConfigurationOption), "SetEquationAndConfigurationOption"),
        (nameof(IEquationTarget.Delete), "Delete"),
    };

    /// <summary>In interface order.</summary>
    public static readonly IReadOnlyList<(string Member, string Key)> MassProperty = new[]
    {
        (nameof(IMassPropertyReading.SetAccuracyLevel), "set_AccuracyLevel"),
        (nameof(IMassPropertyReading.SetSelectedItems), "set_SelectedItems"),
        (nameof(IMassPropertyReading.SetUseSystemUnits), "set_UseSystemUnits"),
        (nameof(IMassPropertyReading.Recalculate), "Recalculate"),
        (nameof(IMassPropertyReading.GetVolume), "get_Volume"),
        (nameof(IMassPropertyReading.GetSurfaceArea), "get_SurfaceArea"),
        (nameof(IMassPropertyReading.GetCenterOfMass), "get_CenterOfMass"),
        (nameof(IMassPropertyReading.GetPrincipalMomentsOfInertia), "get_PrincipalMomentsOfInertia"),
        (nameof(IMassPropertyReading.GetMass), "get_Mass"),
        (nameof(IMassPropertyReading.GetDensity), "get_Density"),
    };

    public static IEnumerable<object[]> EquationMembers() => Equation.Select(row => new object[] { row.Member });

    public static IEnumerable<object[]> MassPropertyMembers() => MassProperty.Select(row => new object[] { row.Member });

    public static string EquationKey(string member) => Equation.Single(row => row.Member == member).Key;

    public static string MassPropertyKey(string member) => MassProperty.Single(row => row.Member == member).Key;

    /// <summary>One call of <paramref name="member"/>; what it answered, or null for a void member.</summary>
    public static object? CallEquation(IEquationTarget target, string member)
    {
        switch (member)
        {
            case nameof(IEquationTarget.GetCount):
                return target.GetCount();
            case nameof(IEquationTarget.GetEquation):
                return target.GetEquation(4);
            case nameof(IEquationTarget.Add3):
                return target.Add3(2, AddedText, true, 1, ConfigNames);
            case nameof(IEquationTarget.Add2):
                return target.Add2(3, AddedText, false);
            case nameof(IEquationTarget.SetEquation):
                target.SetEquation(1, EditedText);
                return null;
            case nameof(IEquationTarget.SetEquationAndConfigurationOption):
                return target.SetEquationAndConfigurationOption(0, EditedText, 2, null);
            case nameof(IEquationTarget.Delete):
                return target.Delete(5);
            default:
                throw new ArgumentOutOfRangeException(nameof(member), member, "Not a member of IEquationTarget.");
        }
    }

    /// <summary>The arguments <see cref="CallEquation"/> hands the interop member, in its order.</summary>
    public static object?[] EquationArguments(string member)
    {
        switch (member)
        {
            case nameof(IEquationTarget.GetCount):
                return new object?[0];
            case nameof(IEquationTarget.GetEquation):
                return new object?[] { 4 };
            case nameof(IEquationTarget.Add3):
                return new object?[] { 2, AddedText, true, 1, ConfigNames };
            case nameof(IEquationTarget.Add2):
                return new object?[] { 3, AddedText, false };
            case nameof(IEquationTarget.SetEquation):
                return new object?[] { 1, EditedText };
            case nameof(IEquationTarget.SetEquationAndConfigurationOption):
                return new object?[] { 0, EditedText, 2, null };
            case nameof(IEquationTarget.Delete):
                return new object?[] { 5 };
            default:
                throw new ArgumentOutOfRangeException(nameof(member), member, "Not a member of IEquationTarget.");
        }
    }

    /// <summary>One call of <paramref name="member"/>; what it answered, or null for a void member.</summary>
    public static object? CallMassProperty(IMassPropertyReading target, string member)
    {
        switch (member)
        {
            case nameof(IMassPropertyReading.SetAccuracyLevel):
                target.SetAccuracyLevel(RemodelGeometry.HigherAccuracy);
                return null;
            case nameof(IMassPropertyReading.SetSelectedItems):
                target.SetSelectedItems(Bodies);
                return null;
            case nameof(IMassPropertyReading.SetUseSystemUnits):
                target.SetUseSystemUnits(true);
                return null;
            case nameof(IMassPropertyReading.Recalculate):
                return target.Recalculate();
            case nameof(IMassPropertyReading.GetVolume):
                return target.GetVolume();
            case nameof(IMassPropertyReading.GetSurfaceArea):
                return target.GetSurfaceArea();
            case nameof(IMassPropertyReading.GetCenterOfMass):
                return target.GetCenterOfMass();
            case nameof(IMassPropertyReading.GetPrincipalMomentsOfInertia):
                return target.GetPrincipalMomentsOfInertia();
            case nameof(IMassPropertyReading.GetMass):
                return target.GetMass();
            case nameof(IMassPropertyReading.GetDensity):
                return target.GetDensity();
            default:
                throw new ArgumentOutOfRangeException(nameof(member), member, "Not a member of IMassPropertyReading.");
        }
    }

    /// <summary>
    /// The arguments <see cref="CallMassProperty"/> hands the interop member. The bodies arrive as
    /// their own array (<see cref="SharedRemodelInteropTests.TheSelectedBodiesAreHandedOverAsAFreshArrayInOrder"/>),
    /// compared here element by element.
    /// </summary>
    public static object?[] MassPropertyArguments(string member)
    {
        switch (member)
        {
            case nameof(IMassPropertyReading.SetAccuracyLevel):
                return new object?[] { RemodelGeometry.HigherAccuracy };
            case nameof(IMassPropertyReading.SetSelectedItems):
                return new object?[] { Bodies };
            case nameof(IMassPropertyReading.SetUseSystemUnits):
                return new object?[] { true };
            case nameof(IMassPropertyReading.Recalculate):
            case nameof(IMassPropertyReading.GetVolume):
            case nameof(IMassPropertyReading.GetSurfaceArea):
            case nameof(IMassPropertyReading.GetCenterOfMass):
            case nameof(IMassPropertyReading.GetPrincipalMomentsOfInertia):
            case nameof(IMassPropertyReading.GetMass):
            case nameof(IMassPropertyReading.GetDensity):
                return new object?[0];
            default:
                throw new ArgumentOutOfRangeException(nameof(member), member, "Not a member of IMassPropertyReading.");
        }
    }

    /// <summary>One product source file, by name, found by the scan the guard audits read.</summary>
    public static string ProductSource(string fileName)
    {
        List<string> matches = DrawingFamilyReadAuditTests.ProductSourceFiles()
            .Where(file => string.Equals(Path.GetFileName(file), fileName, StringComparison.Ordinal))
            .ToList();

        Assert.True(matches.Count == 1, $"Expected one {fileName} in the product source, found {matches.Count}.");
        return File.ReadAllText(matches[0]).Replace("\r\n", "\n");
    }
}

/// <summary>
/// The tables above cover every member of both interfaces, so a member added to either one is a
/// red test until its bare key and its call are written down.
/// </summary>
public class ProbeWrapperCasesTests
{
    [Fact]
    public void TheEquationTableIsEveryMemberOfIEquationTarget() =>
        Assert.Equal(
            typeof(IEquationTarget).GetMethods().Select(method => method.Name).OrderBy(name => name, StringComparer.Ordinal),
            ProbeWrapperCases.Equation.Select(row => row.Member).OrderBy(name => name, StringComparer.Ordinal));

    [Fact]
    public void TheMassPropertyTableIsEveryMemberOfIMassPropertyReading() =>
        Assert.Equal(
            typeof(IMassPropertyReading).GetMethods().Select(method => method.Name).OrderBy(name => name, StringComparer.Ordinal),
            ProbeWrapperCases.MassProperty.Select(row => row.Member).OrderBy(name => name, StringComparer.Ordinal));

    /// <summary>Each key is a member the interop really declares on the interface the shared class maps onto.</summary>
    [Fact]
    public void EveryKeyIsAMemberTheInteropDeclares()
    {
        var equationMembers = new HashSet<string>(typeof(IEquationMgr).GetMethods().Select(method => method.Name), StringComparer.Ordinal);
        var massPropertyMembers = new HashSet<string>(typeof(IMassProperty2).GetMethods().Select(method => method.Name), StringComparer.Ordinal);

        Assert.All(ProbeWrapperCases.Equation, row => Assert.Contains(row.Key, equationMembers));
        Assert.All(ProbeWrapperCases.MassProperty, row => Assert.Contains(row.Key, massPropertyMembers));
    }
}

/// <summary>Every key a gate was asked about, in order and with repeats, and every refusal.</summary>
internal sealed class GateCallLog : ISwGateObserver
{
    public List<string> Keys { get; } = new List<string>();

    public List<MutatingCallError> Refusals { get; } = new List<MutatingCallError>();

    public void Gated(string interopMember) => Keys.Add(interopMember);

    public void Refused(MutatingCallError refusal) => Refusals.Add(refusal);
}

/// <summary>
/// A stand-in for one SOLIDWORKS interop interface that records every member called on it, under
/// the name the interop declares it by (a property read is <c>get_X</c>, a write <c>set_X</c>),
/// with its arguments, and answers what the test set for that member - or the return type's
/// default. A transparent proxy, so a test can name the interop type without writing out its
/// thirty-odd members; no COM object exists and SOLIDWORKS is never started.
/// </summary>
internal sealed class InteropRecorder<TInterface> : RealProxy
    where TInterface : class
{
    private readonly Dictionary<string, object?> _answers = new Dictionary<string, object?>(StringComparer.Ordinal);
    private readonly Dictionary<string, Exception> _failures = new Dictionary<string, Exception>(StringComparer.Ordinal);

    public InteropRecorder()
        : base(typeof(TInterface))
    {
    }

    public TInterface Instance => (TInterface)GetTransparentProxy();

    /// <summary>Every member called, in order, with the arguments it was handed.</summary>
    public List<(string Member, object?[] Arguments)> Calls { get; } = new List<(string, object?[])>();

    public InteropRecorder<TInterface> Answer(string member, object? answer)
    {
        _answers[member] = answer;
        return this;
    }

    public InteropRecorder<TInterface> Fail(string member, Exception failure)
    {
        _failures[member] = failure;
        return this;
    }

    public override IMessage Invoke(IMessage message)
    {
        var call = (IMethodCallMessage)message;
        Calls.Add((call.MethodName, call.Args));

        if (_failures.TryGetValue(call.MethodName, out Exception? failure))
        {
            return new ReturnMessage(failure, call);
        }

        Type returns = ((MethodInfo)call.MethodBase).ReturnType;
        object? answer = _answers.TryGetValue(call.MethodName, out object? set)
            ? set
            : returns.IsValueType && returns != typeof(void) ? Activator.CreateInstance(returns) : null;

        return new ReturnMessage(answer, null, 0, call.LogicalCallContext, call);
    }
}
