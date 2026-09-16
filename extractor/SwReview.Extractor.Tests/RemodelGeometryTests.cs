using System;
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

    [Fact]
    public void BuildsTheMassPropertyAtHigherAccuracyOverTheSolidBodies()
    {
        GeometryReading reading = Read();

        // The integer, not the name: swMassPropertyAccuracyLevel_Higher = 2 (VERIFIED value).
        Assert.Equal(2, MassProperty.AccuracyLevel);
        Assert.Equal(2, reading.AccuracyLevel);

        // SelectedItems is the solid bodies, so the reading is of the part rather than of
        // whatever the engineer last clicked.
        Assert.Equal(
            _harness.Copy.SolidBodies.Cast<object>().ToArray(),
            MassProperty.SelectedItems!.ToArray());

        Assert.Contains("CreateMassProperty2", _harness.Observer.Members);
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
        foreach (string member in _harness.Observer.Members.Skip(alreadySeen))
        {
            Assert.Contains(RemodelInteropSurface.Calls, call => call.Member == member);
        }

        // The typed members, by name, so a rewrite through the raw object fails here.
        foreach (string member in new[]
        {
            "CreateMassProperty2", "set_AccuracyLevel", "set_SelectedItems", "Recalculate",
            "get_Volume", "get_SurfaceArea", "get_CenterOfMass", "get_PrincipalMomentsOfInertia",
            "get_Mass", "get_Density",
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

    [Fact]
    public void SumsTheFaceAndEdgeCountsOverEverySolidBody()
    {
        _harness.Copy.SolidBodies.Add(new FakeBody(faceCount: 10, edgeCount: 15));

        GeometryReading reading = Read();

        Assert.Equal(2, reading.SolidBodyCount);
        Assert.Equal(16, reading.FaceCount);
        Assert.Equal(27, reading.EdgeCount);
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
