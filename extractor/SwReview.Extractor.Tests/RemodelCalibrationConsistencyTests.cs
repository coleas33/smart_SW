using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Sw;
using SwReview.Extractor.Tests.Fakes;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>T187: the gate and calibration use whole-part/default readings; overrides fail closed.</summary>
public class RemodelCalibrationConsistencyTests
{
    [Theory]
    [InlineData("GetOverrideMass", "get_OverrideMass")]
    [InlineData("GetOverrideCenterOfMass", "get_OverrideCenterOfMass")]
    [InlineData("GetOverrideMomentsOfInertia", "get_OverrideMomentsOfInertia")]
    public void SharedAndGatedOverrideMappingsReadEachNativeFlagOnce(string seam, string native)
    {
        var options = new InteropRecorder<IMassPropertyOverrideOptions>().Answer(native, true);
        var properties = new InteropRecorder<IMassProperty2>().Answer("GetOverrideOptions", options.Instance);
        var observer = new RecordingGateObserver();
        var gate = new SwGate(SwReview.Extractor.Console.Program.RemodelProbeGate(observer).Breaker,
            new RemodelProbeGuard()) { Observer = observer };
        var target = new GatedMassPropertyReading(gate, new SwMassProperty(properties.Instance));

        MethodInfo? get = typeof(GatedMassPropertyReading).GetMethod("GetOverrideOptions");
        Assert.NotNull(get);
        object? reading = get!.Invoke(target, null);
        Assert.NotNull(reading);
        Assert.Equal(true, reading!.GetType().GetMethod(seam)!.Invoke(reading, null));

        Assert.Equal(new[] { "GetOverrideOptions", native }, observer.Members);
        Assert.Equal("GetOverrideOptions", Assert.Single(properties.Calls).Member);
        Assert.Equal(native, Assert.Single(options.Calls).Member);
        Assert.Empty(observer.Refusals);
    }

    [Theory]
    [InlineData("mass", "SetOverrideMassValue")]
    [InlineData("center_of_mass", "SetOverrideCenterOfMassValue")]
    [InlineData("moments", "SetOverridePrincipalMomentsOfInertia")]
    public void ProbeNativeOverrideSetupUsesOneIndependentFlagAndKnownSIValueWithoutSaving(string kind, string setter)
    {
        var options = new InteropRecorder<IMassPropertyOverrideOptions>().Answer(setter, true);
        var properties = new InteropRecorder<IMassProperty2>().Answer("GetOverrideOptions", options.Instance)
            .Answer("SetOverrideOptions", true);
        (SwRemodelProbeHost host, RemodelProbePart part, InteropRecorder<IModelDoc2> document) = NativeHost(properties);

        MethodInfo? apply = typeof(SwRemodelProbeHost).GetMethod("ApplyMassPropertyOverride");
        Assert.NotNull(apply);
        apply!.Invoke(host, new object[] { part, kind });

        Assert.Equal(new[] { "set_OverrideMass", "set_OverrideCenterOfMass", "set_OverrideMomentsOfInertia", setter },
            options.Calls.Select(call => call.Member));
        Assert.Equal(kind == "mass", options.Calls[0].Arguments[0]);
        Assert.Equal(kind == "center_of_mass", options.Calls[1].Arguments[0]);
        Assert.Equal(kind == "moments", options.Calls[2].Arguments[0]);
        if (kind == "mass") Assert.Equal(123.0, options.Calls[3].Arguments[0]);
        else Assert.Equal(kind == "center_of_mass" ? new[] { 0.013, 0.017, 0.019 } : new[] { 0.101, 0.202, 0.303 },
            Assert.IsType<double[]>(options.Calls[3].Arguments[0]));
        if (kind == "center_of_mass") Assert.Equal(string.Empty, options.Calls[3].Arguments[1]);
        var applied = Assert.Single(properties.Calls, call => call.Member == "SetOverrideOptions");
        Assert.Same(options.Instance, applied.Arguments[0]);
        Assert.Equal(1, applied.Arguments[1]);
        Assert.Null(applied.Arguments[2]);
        Assert.Equal("ClearSelection2", document.Calls[0].Member);
        Assert.DoesNotContain(document.Calls, call => call.Member.StartsWith("Save", StringComparison.Ordinal));
    }

    [Theory]
    [InlineData(false, true)]
    [InlineData(true, false)]
    public void ProbeNativeOverrideSetupChecksBothSetterBooleansBeforeMeasuring(bool valueSet, bool applied)
    {
        var options = new InteropRecorder<IMassPropertyOverrideOptions>().Answer("SetOverrideMassValue", valueSet);
        var properties = new InteropRecorder<IMassProperty2>().Answer("GetOverrideOptions", options.Instance)
            .Answer("SetOverrideOptions", applied);
        (SwRemodelProbeHost host, RemodelProbePart part, _) = NativeHost(properties);

        MethodInfo? apply = typeof(SwRemodelProbeHost).GetMethod("ApplyMassPropertyOverride");
        Assert.NotNull(apply);
        TargetInvocationException failure = Assert.Throws<TargetInvocationException>(() => apply!.Invoke(host, new object[] { part, "mass" }));

        Assert.IsType<InvalidOperationException>(failure.InnerException);
        Assert.DoesNotContain(properties.Calls, call => call.Member == "Recalculate" || call.Member == "get_Volume");
        if (!valueSet) Assert.DoesNotContain(properties.Calls, call => call.Member == "SetOverrideOptions");
    }

    [Fact]
    public void ProbeNativePlainReadingClearsSelectionWithoutSelectingBodiesOrChangingAccuracy()
    {
        var properties = new InteropRecorder<IMassProperty2>();
        (SwRemodelProbeHost host, RemodelProbePart part, InteropRecorder<IModelDoc2> document) = NativeHost(properties);

        Assert.NotNull(host.MeasureMassProperties(part));

        Assert.Equal("ClearSelection2", document.Calls[0].Member);
        Assert.Empty(properties.Calls);
    }

    [Theory]
    [InlineData("IMassProperty2.SetOverrideOptions")]
    [InlineData("IMassPropertyOverrideOptions.set_OverrideMass")]
    [InlineData("IMassPropertyOverrideOptions.set_OverrideCenterOfMass")]
    [InlineData("IMassPropertyOverrideOptions.set_OverrideMomentsOfInertia")]
    [InlineData("IMassPropertyOverrideOptions.SetOverrideMassValue")]
    [InlineData("IMassPropertyOverrideOptions.SetOverrideCenterOfMassValue")]
    [InlineData("IMassPropertyOverrideOptions.SetOverridePrincipalMomentsOfInertia")]
    public void OverrideFixtureWritesAreProbeOnlyAndNeverBecomeStageOneOrReviewWrites(string member)
    {
        Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert(member));
        Assert.Throws<MutatingCallError>(() => new RemodelGuard().Assert(member));
        new RemodelProbeGuard().Assert(member);
    }

    [Theory]
    [InlineData("mass")]
    [InlineData("center_of_mass")]
    [InlineData("moments")]
    public void GeometryRejectsEachOverrideBeforeAnyRecalculateOrMeasuredGetter(string kind)
    {
        using var harness = Harness();
        FakeMassProperty mass = harness.Copy.MassProperty!;
        SetKind(mass, kind);

        GeometryReading reading = RemodelHarness.Ok<GeometryReading>(harness.Dispatch(RemodelCommands.Geometry, "{}"));

        Assert.Equal(RemodelGeometry.StatusUnknownError, reading.Status);
        Assert.False(reading.Recalculated);
        Assert.Null(reading.VolumeM3);
        Assert.Null(reading.SurfaceAreaM2);
        Assert.Null(reading.CenterOfMassM);
        Assert.Null(reading.PrincipalMoments);
        Assert.Null(reading.MassKg);
        Assert.Null(reading.Density);
        Assert.DoesNotContain(nameof(FakeMassProperty.Recalculate), mass.Members);
        Assert.DoesNotContain(nameof(FakeMassProperty.GetVolume), mass.Members);
        Assert.DoesNotContain(nameof(FakeMassProperty.GetMass), mass.Members);
        Assert.DoesNotContain(nameof(FakeMassProperty.GetCenterOfMass), mass.Members);
        Assert.DoesNotContain(nameof(FakeMassProperty.GetPrincipalMomentsOfInertia), mass.Members);
        Assert.Empty(harness.Observer.Refusals);
    }

    [Fact]
    public void GeometryAnUnreadableOverrideObjectStaysUnknownBeforeAnyMeasuredGetter()
    {
        using var harness = Harness();
        harness.Copy.MassProperty!.OverrideOptionsUnreadable = true;

        GeometryReading reading = RemodelHarness.Ok<GeometryReading>(harness.Dispatch(RemodelCommands.Geometry, "{}"));

        Assert.Equal(RemodelGeometry.StatusUnknownError, reading.Status);
        Assert.Null(reading.VolumeM3);
        Assert.Null(reading.MassKg);
        Assert.False(reading.Recalculated);
        Assert.DoesNotContain(nameof(FakeMassProperty.GetVolume), harness.Copy.MassProperty.Members);
    }

    [Fact]
    public void GeometryAnOverrideReadThrowIsAnErrorAndNeverFallsBackToUnprotectedNumbers()
    {
        using var harness = Harness();
        FakeMassProperty mass = harness.Copy.MassProperty!;
        mass.OverrideReadFailure = new InvalidOperationException("fictional override read failed");

        BridgeResponse response = harness.Dispatch(RemodelCommands.Geometry, "{}");

        Assert.Equal("error", response.Status);
        Assert.DoesNotContain(nameof(FakeMassProperty.Recalculate), mass.Members);
        Assert.DoesNotContain(nameof(FakeMassProperty.GetVolume), mass.Members);
    }

    [Fact]
    public void Probe8CalibratesAtTheSameWholePartDefaultAsGeometryWithoutEitherSetter()
    {
        var readings = new List<FakeMassProperty>();
        var host = ScriptedHost(readings);

        RemodelProbeRecord record = Probe(host);

        Assert.Equal(RemodelProbeVerdict.Verified, record.Verdict);
        Assert.Equal("default", record.RawResult["accuracy_level"]);
        Assert.Equal("whole_part", record.RawResult["measurement_scope"]);
        Assert.All(readings, mass =>
        {
            Assert.Equal(-1, mass.AccuracyLevel);
            Assert.Null(mass.SelectedItems);
            Assert.DoesNotContain(nameof(FakeMassProperty.SetAccuracyLevel), mass.Members);
            Assert.DoesNotContain(nameof(FakeMassProperty.SetSelectedItems), mass.Members);
        });
        Assert.DoesNotContain("set_AccuracyLevel", record.InteropMembers);
        Assert.DoesNotContain("set_SelectedItems", record.InteropMembers);
    }

    [Fact]
    public void Probe8RecordsThreeIndependentOverrideExperimentsPerShapeAndClosesBothParts()
    {
        var host = ScriptedHost(new List<FakeMassProperty>());

        RemodelProbeRecord record = Probe(host);

        Assert.Equal(RemodelProbeVerdict.Verified, record.Verdict);
        Assert.Equal(new[] { "mass", "center_of_mass", "moments", "mass", "center_of_mass", "moments" },
            host.Calls.Where(call => call.StartsWith("ApplyMassPropertyOverride:", StringComparison.Ordinal))
                .Select(call => call.Substring("ApplyMassPropertyOverride:".Length)));
        foreach (string shape in new[] { "box", "cylinder" })
        {
            foreach (string kind in new[] { "mass", "center_of_mass", "moments" })
            {
                Assert.Equal("true", record.RawResult[shape + "_" + kind + "_override_detected"]);
                Assert.Equal("true", record.RawResult[shape + "_" + kind + "_override_honoured"]);
            }
        }
        Assert.Equal(2, host.Calls.Count(call => call == nameof(FakeRemodelProbeHost.ClosePart)));
        Assert.Equal(8, host.Calls.Count(call => call == nameof(FakeRemodelProbeHost.MeasureMassProperties)));
    }

    [Theory]
    [InlineData("mass")]
    [InlineData("center_of_mass")]
    [InlineData("moments")]
    public void Probe8RecordsAnOverrideNotHonouredAsObservedInsteadOfClaimingItIs(string kind)
    {
        var host = ScriptedHost(new List<FakeMassProperty>(), notHonoured: kind);

        RemodelProbeRecord record = Probe(host);

        Assert.Equal(RemodelProbeVerdict.Verified, record.Verdict);
        Assert.Equal("true", record.RawResult["box_" + kind + "_override_detected"]);
        Assert.Equal("false", record.RawResult["box_" + kind + "_override_honoured"]);
    }

    [Theory]
    [InlineData("mass")]
    [InlineData("center_of_mass")]
    [InlineData("moments")]
    public void Probe8AnOverrideFlagThatCannotBeDetectedLeavesCalibrationUnresolved(string kind)
    {
        var host = ScriptedHost(new List<FakeMassProperty>(), undetected: kind);

        RemodelProbeRecord record = Probe(host);

        Assert.Equal(RemodelProbeVerdict.Unresolved, record.Verdict);
        Assert.Equal("false", record.RawResult["box_" + kind + "_override_detected"]);
        Assert.Equal(2, host.Calls.Count(call => call == nameof(FakeRemodelProbeHost.ClosePart)));
    }

    [Fact]
    public void Probe8AnUnreadablePlainOverrideObjectNeverProducesCalibrationNumbers()
    {
        var host = new FakeRemodelProbeHost
        {
            MeasureMassPropertiesImpl = _ => new FakeMassProperty { OverrideOptionsUnreadable = true },
        };

        RemodelProbeRecord record = Probe(host);

        Assert.Equal(RemodelProbeVerdict.Unresolved, record.Verdict);
        Assert.DoesNotContain("box_volume_rel_error", record.RawResult.Keys);
        Assert.DoesNotContain("cylinder_volume_rel_error", record.RawResult.Keys);
        Assert.Equal(2, host.Calls.Count(call => call == nameof(FakeRemodelProbeHost.ClosePart)));
    }

    [Theory]
    [InlineData(double.NaN)]
    [InlineData(double.PositiveInfinity)]
    [InlineData(-1.0)]
    [InlineData(0.0)]
    public void Probe8AnInvalidPlainVolumeCannotRecordAVerifiedCalibration(double volume)
    {
        var host = new FakeRemodelProbeHost { MeasureMassPropertiesImpl = _ => new FakeMassProperty { Volume = volume } };

        Assert.Equal(RemodelProbeVerdict.Unresolved, Probe(host).Verdict);
    }

    private static RemodelHarness Harness()
    {
        var harness = new RemodelHarness(new FakeFeature("ref:boss", "Boss-Extrude1"));
        harness.Open();
        return harness;
    }

    private static (SwRemodelProbeHost Host, RemodelProbePart Part, InteropRecorder<IModelDoc2> Document) NativeHost(
        InteropRecorder<IMassProperty2> properties)
    {
        var extension = new InteropRecorder<IModelDocExtension>(typeof(ModelDocExtension)).Answer("CreateMassProperty2", properties.Instance);
        var document = new InteropRecorder<IModelDoc2>().Answer("get_Extension", extension.Instance);
        var application = new InteropRecorder<ISldWorks>();
        SwGate gate = SwReview.Extractor.Console.Program.RemodelProbeGate(new RecordingGateObserver());
        return (new SwRemodelProbeHost(application.Instance, gate),
            new RemodelProbePart(document.Instance, @"C:\Fictional\probe-8-box.SLDPRT", Array.Empty<object>()), document);
    }

    private static RemodelProbeRecord Probe(FakeRemodelProbeHost host)
    {
        var context = new RemodelProbeContext(
            new RemodelProbePart(new object(), @"C:\Fictional\probe-part\remodel-probe.SLDPRT", Array.Empty<object>()),
            new SwGate(), "32.5.0.48", host, @"C:\Fictional");
        return RemodelProbeRunner.Run("PROBE-8", context, RemodelProbeExecutors.ByProbeId);
    }

    private static FakeRemodelProbeHost ScriptedHost(
        List<FakeMassProperty> readings, string? notHonoured = null, string? undetected = null)
    {
        var kinds = new Dictionary<object, string>();
        return new FakeRemodelProbeHost
        {
            ApplyMassPropertyOverrideImpl = (part, kind) => kinds[part.Document] = kind,
            MeasureMassPropertiesImpl = part =>
            {
                string kind = kinds.TryGetValue(part.Document, out string? applied) ? applied : "none";
                var mass = new FakeMassProperty();
                if (kind != undetected) SetKind(mass, kind);
                if (kind != notHonoured)
                {
                    if (kind == "mass") mass.Mass = 123.0;
                    if (kind == "center_of_mass") mass.CenterOfMass = new[] { 0.013, 0.017, 0.019 };
                    if (kind == "moments") mass.PrincipalMoments = new[] { 0.101, 0.202, 0.303 };
                }
                readings.Add(mass);
                return mass;
            },
        };
    }

    private static void SetKind(FakeMassProperty mass, string kind)
    {
        mass.OverrideMass = kind == "mass";
        mass.OverrideCenterOfMass = kind == "center_of_mass";
        mass.OverrideMomentsOfInertia = kind == "moments";
    }
}
