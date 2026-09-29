using System;
using System.Collections.Generic;
using System.Linq;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Tests.Fakes;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T094. <c>remodel.geometry</c>: the measurement half of the geometry gate
/// (contracts/bridge-remodel.md, data-model.md section 3.1).
///
/// <b>Measured in C#, decided in Python.</b> The measurement calls take ByRef out-parameters
/// the Python bridge cannot marshal; the verdict has to be table-testable with no seat. So this
/// suite asserts a <i>reading</i> and never a verdict: there is no pass or fail anywhere in it.
///
/// Four decisions are pinned here because each one has a plausible, wrong alternative:
///
///   * <b>The typed <c>IMassProperty2</c>, never <c>GetMassProperties2</c>'s raw
///     <c>Object</c>.</b> That call answers a flat <c>double[]</c> whose index layout is not
///     discoverable by reflection and has changed across API generations, so a wrong index is a
///     silently wrong number rather than a build error. The assertion is on the recorded member
///     names, which is the only place the choice is visible.
///   * <b><c>Recalculate()</c>'s Boolean is checked before anything is read.</b> An
///     un-recalculated mass property answers the previous body's numbers, and a gate comparing
///     two of those would pass on a part that moved.
///   * <b>The principal moments are sorted ascending by the producer</b>, because two bodies
///     differing by a symmetry-degenerate rotation return the same three numbers permuted.
///   * <b>Mass and the material are recorded separately from geometry.</b> Mass is volume times
///     density and density comes from the material, which is not geometry: a mass-only delta is
///     <c>material_changed</c> and never <c>geometry_changed</c>.
///
/// A <c>swMassPropertiesStatus_e</c> other than <c>OK</c> is <b>reported</b>, and every measured
/// field stays null. Unknown stays unknown: a defaulted zero volume is a number the gate would
/// happily compare.
/// </summary>
public class RemodelGeometryTests : IDisposable
{
    private readonly RemodelHarness _harness;

    public RemodelGeometryTests()
    {
        _harness = new RemodelHarness(
            new FakeFeature("ref:boss", "Boss-Extrude1"),
            new FakeFeature("ref:fillet", "Fillet1"));
        _harness.Open();
    }

    public void Dispose() => _harness.Dispose();

    private FakeMassProperty MassProperty => _harness.Copy.MassProperty!;

    private GeometryReading Read() =>
        RemodelHarness.Ok<GeometryReading>(_harness.Dispatch(RemodelCommands.Geometry, "{}"));

    // ---- how the reading is taken ------------------------------------------------------

    /// <summary>
    /// U27 (default taken 2026-09-28, the owner may revise): the copy is measured as a whole
    /// part, the way the review dump's <c>PropertyDumper</c> measures every part on the seat -
    /// <c>CreateMassProperty2</c>, <c>UseSystemUnits</c>, <c>Recalculate</c>, the getters - and
    /// never with <c>set_SelectedItems</c> or <c>set_AccuracyLevel</c>, the two calls no seat had
    /// run when SOLIDWORKS exited during the first baseline reading. The scope gate refuses a
    /// part with more than one solid body, so the whole part is that one body.
    /// </summary>
    [Fact]
    public void ReadsTheWholePartWithNoSelectionAndNoAccuracySettingAsTheReviewDumpDoes()
    {
        int alreadySeen = _harness.Observer.Members.Count;

        GeometryReading reading = Read();

        Assert.Equal(
            new[]
            {
                nameof(FakeMassProperty.SetUseSystemUnits),
                nameof(FakeMassProperty.Recalculate),
                nameof(FakeMassProperty.GetVolume),
                nameof(FakeMassProperty.GetSurfaceArea),
                nameof(FakeMassProperty.GetCenterOfMass),
                nameof(FakeMassProperty.GetPrincipalMomentsOfInertia),
                nameof(FakeMassProperty.GetMass),
                nameof(FakeMassProperty.GetDensity),
            },
            MassProperty.Members);
        Assert.Null(MassProperty.SelectedItems);
        Assert.Equal(-1, MassProperty.AccuracyLevel);

        // Null says the reading set no accuracy of its own: SOLIDWORKS's default was used.
        Assert.Null(reading.AccuracyLevel);

        string[] gated = _harness.Observer.Members.Skip(alreadySeen).ToArray();
        Assert.Contains("CreateMassProperty2", gated);
        Assert.DoesNotContain("set_SelectedItems", gated);
        Assert.DoesNotContain("set_AccuracyLevel", gated);
        Assert.Empty(_harness.Observer.Refusals);
    }

    /// <summary>
    /// <c>CreateMassProperty2</c>'s remarks: pre-selected bodies are included. A whole-part
    /// reading therefore starts from an empty selection - cleared through the allowlisted
    /// <c>IModelDoc2.ClearSelection2</c> on the copy, behind <c>VerifyTarget</c> - so what the
    /// engineer or a folder change last selected cannot narrow what is measured.
    /// </summary>
    [Fact]
    public void ClearsTheCopysSelectionBeforeTheMassPropertyIsBuilt()
    {
        _harness.Copy.Selected.Add(_harness.Copy.Features[0]);
        int alreadySeen = _harness.Observer.Members.Count;

        Read();

        int cleared = _harness.Copy.Members.IndexOf(nameof(FakeRemodelDocument.ClearSelection));
        int created = _harness.Copy.Members.IndexOf(nameof(FakeRemodelDocument.CreateMassProperty));
        Assert.True(cleared >= 0, "the copy's selection was never cleared.");
        Assert.True(cleared < created, "the selection was cleared after the mass property was built.");
        Assert.Empty(_harness.Copy.Selected);
        Assert.Contains("IModelDoc2.ClearSelection2", _harness.Observer.Members.Skip(alreadySeen));
        Assert.Empty(_harness.Observer.Refusals);
    }

    /// <summary>
    /// The record is named <c>volume_m3</c>, <c>surface_area_m2</c>, <c>center_of_mass_m</c>
    /// and <c>mass_kg</c>, and contracts/bridge-remodel.md says every length is metres. The
    /// interop answers in the <b>document's display units</b> unless <c>UseSystemUnits</c> is
    /// set, and it has to be set <b>before</b> <c>Recalculate</c> or the numbers come back in
    /// those units anyway (research R12; <c>Dump/PropertyDumper.cs</c> learned this already).
    /// A part authored in mm and g would otherwise write a reading whose numbers contradict
    /// its own field names, and every later comparison reads those numbers.
    /// </summary>
    [Fact]
    public void SetsUseSystemUnitsBeforeRecalculateSoTheNumbersAreMetresAndKilograms()
    {
        Read();

        int units = MassProperty.Members.IndexOf(nameof(FakeMassProperty.SetUseSystemUnits));
        int recalculated = MassProperty.Members.IndexOf(nameof(FakeMassProperty.Recalculate));

        Assert.True(units >= 0, "UseSystemUnits was never set, so the units are the document's.");
        Assert.True(units < recalculated, "UseSystemUnits was set after Recalculate, which is too late.");
        Assert.True(MassProperty.UseSystemUnits);

        // And it is on the frozen interop surface, so an upgrade that moves its signature is a
        // red build rather than a wrong number.
        Assert.Contains("set_UseSystemUnits", _harness.Observer.Members);
        Assert.Contains(
            RemodelInteropSurface.Calls,
            call => call.Key == "IMassProperty2.set_UseSystemUnits");
    }

    [Fact]
    public void ChecksRecalculateBeforeReadingAnything()
    {
        Read();

        int recalculated = MassProperty.Members.IndexOf("Recalculate");
        Assert.True(recalculated >= 0, "Recalculate() was never called.");

        int firstRead = MassProperty.Members.FindIndex(
            member => member.StartsWith("Get", StringComparison.Ordinal));
        Assert.True(firstRead > recalculated, "a value was read before Recalculate() answered.");
    }

    [Fact]
    public void UsesTheTypedInterfaceAndNeverTheRawMassPropertiesObject()
    {
        int alreadySeen = _harness.Observer.Members.Count;

        Read();

        Assert.DoesNotContain("GetMassProperties2", _harness.Observer.Members);

        // It is not on the frozen interop surface either, so no call site can reach it with a
        // signature this build was written against (contracts/interop-manifest.md).
        Assert.DoesNotContain(
            RemodelInteropSurface.Calls,
            call => call.Member == "GetMassProperties2");

        // And every member this reading brought with it is on that frozen surface, so an
        // upgrade that moves one of these signatures is a red build rather than a wrong number.
        // A read is gated by its bare member name and a write - the selection clear before the
        // reading (U27) - by its interface-qualified key.
        foreach (string member in _harness.Observer.Members.Skip(alreadySeen))
        {
            Assert.Contains(RemodelInteropSurface.Calls, call => call.Member == member || call.Key == member);
        }

        // The typed members, by name, so a rewrite through the raw object fails here.
        foreach (string member in new[]
        {
            "CreateMassProperty2", "set_UseSystemUnits", "Recalculate", "get_Volume",
            "get_SurfaceArea", "get_CenterOfMass", "get_PrincipalMomentsOfInertia", "get_Mass",
            "get_Density",
        })
        {
            Assert.Contains(member, _harness.Observer.Members);
        }
    }

    // ---- what the reading carries ------------------------------------------------------

    [Fact]
    public void CarriesTheMeasuredGeometryAndTheBodyFaceAndEdgeCounts()
    {
        MassProperty.Volume = 0.00123456789;
        MassProperty.SurfaceArea = 0.0456;
        MassProperty.CenterOfMass = new[] { 0.01, 0.02, 0.03 };

        GeometryReading reading = Read();

        Assert.Equal(0, reading.Status);
        Assert.True(reading.Recalculated);
        Assert.Equal(0.00123456789, reading.VolumeM3);
        Assert.Equal(0.0456, reading.SurfaceAreaM2);
        Assert.Equal(new[] { 0.01, 0.02, 0.03 }, reading.CenterOfMassM!);

        // One solid body of six faces and twelve edges, and no sheet body.
        Assert.Equal(1, reading.SolidBodyCount);
        Assert.Equal(0, reading.SheetBodyCount);
        Assert.Equal(6, reading.FaceCount);
        Assert.Equal(12, reading.EdgeCount);

        // Tier 2 is stage 2's; the field exists so stage 2 adds a tier rather than a type.
        Assert.Null(reading.Residual);
    }

    /// <summary>
    /// A whole-part reading of two solid bodies is a reading of both at once, which no body
    /// pairing can compare, so it is not taken: the counts are still walked and reported, and
    /// nothing is measured (U27; the scope gate refuses such a part, and the final reading of a
    /// change that split the body says so here rather than passing as a whole).
    /// </summary>
    [Fact]
    public void APartWithMoreThanOneSolidBodyIsCountedButNotMeasuredAsAWhole()
    {
        _harness.Copy.SolidBodies.Add(new FakeBody(faceCount: 10, edgeCount: 15));

        GeometryReading reading = Read();

        Assert.Equal(RemodelGeometry.StatusUnknownError, reading.Status);
        Assert.False(reading.Recalculated);
        Assert.Equal(2, reading.SolidBodyCount);
        Assert.Equal(16, reading.FaceCount);
        Assert.Equal(27, reading.EdgeCount);
        AssertNothingMeasured(reading);
        Assert.DoesNotContain(nameof(FakeRemodelDocument.CreateMassProperty), _harness.Copy.Members);
        Assert.Empty(MassProperty.Members);
    }

    /// <summary>
    /// A solid body has a positive, finite volume. Anything else - zero, negative, not a number,
    /// infinite - is a reading nobody can compare, so it stops there, is reported as not OK and
    /// is never counted as a baseline (U27).
    /// </summary>
    [Theory]
    [InlineData(0.0)]
    [InlineData(-1e-9)]
    [InlineData(double.NaN)]
    [InlineData(double.PositiveInfinity)]
    public void AVolumeThatIsNotPositiveAndFiniteIsNotAUsableReading(double volume)
    {
        MassProperty.Volume = volume;

        GeometryReading reading = Read();

        Assert.Equal(RemodelGeometry.StatusUnknownError, reading.Status);
        Assert.True(reading.Recalculated);
        AssertNothingMeasured(reading);
        Assert.Equal(
            new[]
            {
                nameof(FakeMassProperty.SetUseSystemUnits),
                nameof(FakeMassProperty.Recalculate),
                nameof(FakeMassProperty.GetVolume),
            },
            MassProperty.Members);

        // Not a baseline: the next reading is still the one taken before any change.
        Assert.Equal(RemodelGeometrySubjects.CopyAtOpen, Read().Subject);
    }

    [Fact]
    public void AFaceCountThatCannotBeReadStaysUnknownRatherThanBecomingZero()
    {
        _harness.Copy.SolidBodies[0].FaceCount = null;

        GeometryReading reading = Read();

        Assert.Null(reading.FaceCount);
        Assert.Equal(12, reading.EdgeCount);

        // The rest of the reading is still good; one unreadable count is not a failed reading.
        Assert.Equal(0, reading.Status);
    }

    [Fact]
    public void SortsThePrincipalMomentsAscending()
    {
        // The same body, measured after a symmetry-degenerate rotation: the same three numbers,
        // permuted. Sorting is what makes the comparison a comparison of the body.
        MassProperty.PrincipalMoments = new[] { 3.3e-5, 1.1e-5, 2.2e-5 };

        GeometryReading reading = Read();

        Assert.Equal(new[] { 1.1e-5, 2.2e-5, 3.3e-5 }, reading.PrincipalMoments!);
    }

    [Fact]
    public void RecordsMassAndTheMaterialSeparatelyFromGeometry()
    {
        MassProperty.Mass = 3.21;
        MassProperty.Density = 2700.0;
        _harness.Copy.MaterialName = "1060 Alloy";

        GeometryReading reading = Read();

        Assert.Equal(3.21, reading.MassKg);
        Assert.Equal(2700.0, reading.Density);
        Assert.Equal("1060 Alloy", reading.MaterialName);

        // Its own VERIFIED call, and not a number derived from the volume.
        Assert.Contains("GetMaterialPropertyName2", _harness.Observer.Members);
    }

    [Fact]
    public void AMaterialThatCannotBeReadStaysUnknown()
    {
        _harness.Copy.MaterialName = null;

        Assert.Null(Read().MaterialName);
    }

    // ---- the status, reported and never defaulted ---------------------------------------

    [Fact]
    public void ARecalculateThatAnswersFalseIsReportedAndNothingIsRead()
    {
        MassProperty.RecalculateAnswer = false;

        GeometryReading reading = Read();

        Assert.Equal(1, reading.Status);
        Assert.False(reading.Recalculated);

        AssertNothingMeasured(reading);
        Assert.DoesNotContain(
            MassProperty.Members, member => member.StartsWith("Get", StringComparison.Ordinal));

        // The reading still says which part it is of, and what the bodies were.
        Assert.Equal(1, reading.SolidBodyCount);
        Assert.Equal(_harness.Copy.MaterialName, reading.MaterialName);
    }

    [Fact]
    public void APartWithNoSolidBodyIsReportedAsNoBodyRatherThanAsZeroVolume()
    {
        _harness.Copy.SolidBodies.Clear();

        GeometryReading reading = Read();

        // swMassPropertiesStatus_NoBody = 2 (VERIFIED value).
        Assert.Equal(2, reading.Status);
        Assert.False(reading.Recalculated);
        Assert.Equal(0, reading.SolidBodyCount);
        AssertNothingMeasured(reading);

        // There was nothing to select, so no mass property was built at all.
        Assert.DoesNotContain("CreateMassProperty2", _harness.Observer.Members);
    }

    [Fact]
    public void AMassPropertyThatCannotBeBuiltIsReportedRatherThanDefaulted()
    {
        _harness.Copy.MassProperty = null;

        GeometryReading reading = Read();

        Assert.Equal(1, reading.Status);
        Assert.False(reading.Recalculated);
        AssertNothingMeasured(reading);
    }

    // ---- what the caller may ask for ----------------------------------------------------

    [Fact]
    public void TheSubjectIsStampedByTheRunsOwnPhaseAndNeverByTheCaller()
    {
        // The reading taken before the first change is the baseline; every later one is the
        // after. The caller sends `{}` and so cannot ask for a reading of anything else.
        Assert.Equal(RemodelGeometrySubjects.CopyAtOpen, Read().Subject);
        Assert.Equal(RemodelGeometrySubjects.CopyAtEnd, Read().Subject);
        Assert.Equal(RemodelGeometrySubjects.CopyAtEnd, Read().Subject);
    }

    [Fact]
    public void BothReadingsCarryTheAttestedHashOfTheSourceTheCopyWasMadeFrom()
    {
        // FR-037: the source is never opened for this comparison, in any mode. The baseline
        // stands for it because the copy is a byte-for-byte File.Copy whose SHA-256 was taken
        // before any document handle existed, and the reading says so on its face.
        GeometryReading baseline = Read();
        GeometryReading after = Read();

        Assert.False(string.IsNullOrEmpty(baseline.SourceSha256));
        Assert.Equal(baseline.SourceSha256, after.SourceSha256);
        Assert.DoesNotContain(
            _harness.Seat.Opened,
            path => !string.Equals(path, _harness.CopyPath, StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void TheReadingIsTimestamped()
    {
        DateTime before = DateTime.UtcNow.AddSeconds(-1);

        GeometryReading reading = Read();

        Assert.True(reading.At >= before && reading.At <= DateTime.UtcNow.AddSeconds(1));
    }

    /// <summary>
    /// U27: every call the reading makes has a <c>before</c> marker handed to the host's writer
    /// before the call starts - asserted from inside each fake call, the only moment that proves
    /// it - and an <c>after</c> marker once it answers, pair by pair, in the exact order the
    /// reading makes them. A call that throws leaves <c>failed</c> in place of <c>after</c>.
    /// </summary>
    [Fact]
    public void EveryGeometryCallHasABeforeMarkerWrittenBeforeItStartsAndAnAfterMarkerOnceItAnswers()
    {
        var markers = new List<string>();
        _harness.Services.RemodelStage = (command, marker) =>
        {
            Assert.Equal(RemodelCommands.Geometry, command);
            markers.Add(marker);
        };
        Action<string> inside = member => Assert.True(
            markers.Count > 0 && markers[markers.Count - 1].StartsWith("before ", StringComparison.Ordinal),
            member + " ran before its before-marker was written.");
        _harness.Copy.DuringCall = inside;
        MassProperty.DuringCall = inside;

        Read();

        Assert.Equal(
            Paired(
                "IModelDoc2.ClearSelection2",
                "GetBodies2:solid",
                "GetBodies2:sheet",
                "GetMaterialPropertyName2",
                "GetFaceCount",
                "GetEdgeCount",
                "CreateMassProperty2",
                "set_UseSystemUnits",
                "Recalculate",
                "get_Volume",
                "get_SurfaceArea",
                "get_CenterOfMass",
                "get_PrincipalMomentsOfInertia",
                "get_Mass",
                "get_Density"),
            markers);

        markers.Clear();
        _harness.Copy.GetBodiesFailure = new InvalidOperationException("unreadable bodies");
        Assert.Equal("error", _harness.Dispatch(RemodelCommands.Geometry, "{}").Status);
        Assert.Equal(
            new[]
            {
                "before IModelDoc2.ClearSelection2",
                "after IModelDoc2.ClearSelection2",
                "before GetBodies2:solid",
                "failed GetBodies2:solid",
            },
            markers);
    }

    [Fact]
    public void DiagnosticWriterFailureDoesNotChangeTheMeasurement()
    {
        _harness.Services.RemodelStage = (_, _) => throw new System.IO.IOException("log unavailable");

        Assert.Equal(RemodelGeometry.StatusOk, Read().Status);
    }

    [Fact]
    public void FailedGeometryAttemptsDoNotCountAsReadingsThatPermitSave()
    {
        _harness.Copy.GetBodiesFailure = new InvalidOperationException("unreadable bodies");
        _harness.Dispatch(RemodelCommands.Geometry, "{}");
        _harness.Dispatch(RemodelCommands.Geometry, "{}");
        _harness.Copy.GetBodiesFailure = null;

        Assert.Equal(RemodelErrorCodes.GateNotPassed,
            RemodelHarness.Refusal(_harness.Dispatch(
                RemodelCommands.Save, RemodelHarness.SaveParams(RemodelGateVerdicts.Pass))));
    }

    [Theory]
    [InlineData("recalculate false")]
    [InlineData("no mass property")]
    [InlineData("no solid body")]
    public void ReturnedFailedMeasurementKeepsTheBaselineSubjectAndCannotPermitSave(string failure)
    {
        if (failure == "recalculate false")
        {
            MassProperty.RecalculateAnswer = false;
        }
        else if (failure == "no mass property")
        {
            _harness.Copy.MassProperty = null;
        }
        else
        {
            _harness.Copy.SolidBodies.Clear();
        }

        GeometryReading first = Read();
        GeometryReading second = Read();
        Assert.Equal(RemodelGeometrySubjects.CopyAtOpen, first.Subject);
        Assert.Equal(RemodelGeometrySubjects.CopyAtOpen, second.Subject);
        Assert.NotEqual(RemodelGeometry.StatusOk, second.Status);

        BridgeResponse save = _harness.Dispatch(
            RemodelCommands.Save, RemodelHarness.SaveParams(RemodelGateVerdicts.Pass));
        Assert.Equal(RemodelErrorCodes.GateNotPassed, RemodelHarness.Refusal(save));
        Assert.Equal("0", Assert.IsType<RemodelErrorResult>(save.Result).Detail!["geometry_readings"]);
        Assert.DoesNotContain(nameof(FakeRemodelDocument.Save), _harness.Copy.Members);

        if (_harness.Copy.SolidBodies.Count == 0)
        {
            _harness.Copy.SolidBodies.Add(new FakeBody(faceCount: 6, edgeCount: 12));
        }
        _harness.Copy.MassProperty = new FakeMassProperty();
        Assert.Equal(RemodelGeometrySubjects.CopyAtOpen, Read().Subject);
        Assert.Equal(RemodelGeometrySubjects.CopyAtEnd, Read().Subject);
    }

    [Fact]
    public void BeforeOpenThereIsNoCopyToMeasureAndTheCommandIsRefused()
    {
        using (var fresh = new RemodelHarness(new FakeFeature("ref:boss", "Boss-Extrude1")))
        {
            Assert.Equal(
                RemodelErrorCodes.TargetMismatch,
                RemodelHarness.Refusal(fresh.Dispatch(RemodelCommands.Geometry, "{}")));
        }
    }

    // ---- helpers -------------------------------------------------------------------------

    private static string[] Paired(params string[] calls) =>
        calls.SelectMany(call => new[] { "before " + call, "after " + call }).ToArray();

    private static void AssertNothingMeasured(GeometryReading reading)
    {
        Assert.NotEqual(0, reading.Status);
        Assert.Null(reading.VolumeM3);
        Assert.Null(reading.SurfaceAreaM2);
        Assert.Null(reading.CenterOfMassM);
        Assert.Null(reading.PrincipalMoments);
        Assert.Null(reading.MassKg);
        Assert.Null(reading.Density);
    }
}
