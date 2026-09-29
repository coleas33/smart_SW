using System;
using System.Collections.Generic;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Rms;

/// <summary>
/// The typed <c>IMassProperty2</c>, as the geometry reading addresses it. One member per
/// VERIFIED interop call, so the reading is testable without a SOLIDWORKS seat.
///
/// It is the typed interface and <b>not</b> <c>IModelDocExtension.GetMassProperties2</c>'s raw
/// <c>Object</c>: that call answers a flat <c>double[]</c> whose index layout is not
/// discoverable by reflection and has changed across API generations, so a wrong index there is
/// a silently wrong number rather than a build error. There is deliberately no member here that
/// returns one.
/// </summary>
public interface IMassPropertyReading
{
    /// <summary>
    /// <c>IMassProperty2.set_AccuracyLevel</c>; always <c>Higher = 2</c>. PROBE-8 sets it; the
    /// copy's reading does not (U27, default taken 2026-09-28, the owner may revise), until
    /// PROBE-8 has run it on a seat.
    /// </summary>
    void SetAccuracyLevel(int accuracyLevel);

    /// <summary>
    /// <c>IMassProperty2.set_SelectedItems</c>: the solid bodies, and nothing else. PROBE-8 sets
    /// it on its throwaway part; the copy's reading measures the whole part instead (U27).
    /// </summary>
    void SetSelectedItems(IReadOnlyList<object> bodies);

    /// <summary>
    /// <c>IMassProperty2.set_UseSystemUnits</c>; always <c>true</c>, and always <b>before</b>
    /// <see cref="Recalculate"/>. The interop answers in the document's display units
    /// otherwise, and a part authored in mm and g would fill a record whose fields are named
    /// <c>volume_m3</c> and <c>mass_kg</c> with numbers that are neither (research R12, the
    /// same lesson <c>Dump/PropertyDumper.cs</c> already carries).
    /// </summary>
    void SetUseSystemUnits(bool useSystemUnits);

    /// <summary>
    /// <c>IMassProperty2.Recalculate()</c>. Its Boolean is checked <b>before</b> anything is
    /// read: an un-recalculated mass property answers the previous body's numbers.
    /// </summary>
    bool Recalculate();

    /// <summary><c>IMassProperty2.get_Volume</c>, in cubic metres.</summary>
    double GetVolume();

    /// <summary><c>IMassProperty2.get_SurfaceArea</c>, in square metres.</summary>
    double GetSurfaceArea();

    /// <summary>
    /// <c>IMassProperty2.get_CenterOfMass</c>, three metres. Null - or any length but three -
    /// is unreadable, and stays unknown rather than becoming the origin.
    /// </summary>
    IReadOnlyList<double>? GetCenterOfMass();

    /// <summary><c>IMassProperty2.get_PrincipalMomentsOfInertia</c>, three values. Null is unreadable.</summary>
    IReadOnlyList<double>? GetPrincipalMomentsOfInertia();

    /// <summary><c>IMassProperty2.get_Mass</c>. Compared separately from geometry.</summary>
    double GetMass();

    /// <summary><c>IMassProperty2.get_Density</c>. Density comes from the material, not the shape.</summary>
    double GetDensity();
}

/// <summary>
/// The reads <see cref="RemodelGeometry"/> makes on the copy, and nothing else, so the reading
/// is exercised against a fake exactly as the rest of the remodel seam is.
/// </summary>
public interface IGeometrySource
{
    /// <summary><c>IModelDocExtension.CreateMassProperty2()</c> (VERIFIED). Null is a failed create.</summary>
    IMassPropertyReading? CreateMassProperty();

    /// <summary>
    /// <c>IPartDoc.GetBodies2(BodyType, BVisibleOnly: false)</c> (VERIFIED). Null is "there are
    /// none", which is what the API answers for a part with no body of that type.
    ///
    /// The bodies themselves, and not just a count: the mass property is taken over them and
    /// the face and edge counts are walked from them. <see cref="IScopeSignalSource.GetBodyCount"/>
    /// stays a count because the scope probe reads the engineer's <b>source</b> and hands back
    /// measurements rather than objects.
    /// </summary>
    IReadOnlyList<object>? GetBodies(int bodyType);

    /// <summary><c>IBody2.GetFaceCount()</c> (VERIFIED). Null is unreadable, never zero.</summary>
    int? GetFaceCount(object body);

    /// <summary><c>IBody2.GetEdgeCount()</c> (VERIFIED). Null is unreadable, never zero.</summary>
    int? GetEdgeCount(object body);

    /// <summary>
    /// <c>IPartDoc.GetMaterialPropertyName2(ConfigName, out Database)</c> (VERIFIED), for the
    /// document's active configuration. Null is unknown; the empty string is "no material".
    /// </summary>
    string? GetMaterialName();
}

/// <summary>
/// T095. The <c>remodel.geometry</c> reading (contracts/bridge-remodel.md, data-model.md
/// section 3.1): the mass properties of the run's own copy, measured and never interpreted.
///
/// <b>Measured here, decided in Python.</b> The measurement calls take ByRef out-parameters the
/// Python bridge cannot marshal; the verdict has to be table-testable with no seat. So nothing
/// in this file compares two readings, and nothing in it knows what a tolerance is.
///
/// <b>The whole part, the proven way</b> (U27, default taken 2026-09-28, the owner may revise).
/// SOLIDWORKS exited during the first baseline reading on a seat, after the two calls no seat had
/// run: <c>set_AccuracyLevel</c> and <c>set_SelectedItems</c> - the latter handed a plain
/// <c>object[]</c>, which the programming guide says must be a <c>DispatchWrapper</c> array. The
/// reading now makes the sequence the review dump makes on every part
/// (<c>Dump/PropertyDumper.cs</c>): <c>CreateMassProperty2</c>, <c>UseSystemUnits</c>,
/// <c>Recalculate</c>, the getters, and no selection and no accuracy of its own. A whole-part
/// reading needs guards a selected-body one did not, and each fails closed: more than one solid
/// body is not measured at all; the caller clears the copy's selection first, because
/// pre-selected bodies are included; and a volume that is not positive and finite is not a
/// reading.
///
/// Three rules the shape encodes, each with its own test:
///
///   * <b><c>Recalculate()</c> first.</b> Its Boolean is checked before any value is read, and
///     a false answer ends the reading with every measured field null.
///   * <b>The principal moments are sorted ascending</b>, because two bodies differing by a
///     symmetry-degenerate rotation return the same three numbers permuted, and a comparison of
///     unsorted triples would call them different.
///   * <b>A status other than <c>OK</c> is reported.</b> Unknown stays unknown: a defaulted zero
///     volume is a number the gate would compare and pass.
///
/// Every call is marked before it starts and after it answers
/// (<see cref="RemodelStageMarkers"/>), so a native exit names the call it happened in.
/// </summary>
public static class RemodelGeometry
{
    /// <summary>
    /// <c>swMassPropertyAccuracyLevel_e.swMassPropertyAccuracyLevel_Higher</c> (VERIFIED value 2):
    /// what PROBE-8 measures at. The copy's reading sets no accuracy (U27).
    /// </summary>
    public const int HigherAccuracy =
        (int)swMassPropertyAccuracyLevel_e.swMassPropertyAccuracyLevel_Higher;

    /// <summary><c>swMassPropertiesStatus_e.swMassPropertiesStatus_OK</c> (VERIFIED value 0).</summary>
    public const int StatusOk = (int)swMassPropertiesStatus_e.swMassPropertiesStatus_OK;

    /// <summary>
    /// <c>swMassPropertiesStatus_e.swMassPropertiesStatus_UnknownError</c> (VERIFIED value 1):
    /// the mass property could not be built, <c>Recalculate()</c> answered false, the part has
    /// more than one solid body, or the volume read back was not positive and finite. The typed
    /// interface carries no status member of its own (VERIFIED absence on 32.5.0.48), so the
    /// status is read off what the calls answered rather than out of a field that is not there.
    /// </summary>
    public const int StatusUnknownError =
        (int)swMassPropertiesStatus_e.swMassPropertiesStatus_UnknownError;

    /// <summary>
    /// <c>swMassPropertiesStatus_e.swMassPropertiesStatus_NoBody</c> (VERIFIED value 2): the
    /// part has no solid body, so there is nothing to select and no reading to take.
    /// </summary>
    public const int StatusNoBody = (int)swMassPropertiesStatus_e.swMassPropertiesStatus_NoBody;

    /// <summary><c>swBodyType_e.swSolidBody</c> (VERIFIED value 0).</summary>
    public const int SolidBody = (int)swBodyType_e.swSolidBody;

    /// <summary><c>swBodyType_e.swSheetBody</c> (VERIFIED value 1).</summary>
    public const int SheetBody = (int)swBodyType_e.swSheetBody;

    /// <summary>How many values a centre of mass and a moment triple must have to be readable.</summary>
    private const int Triple = 3;

    // The bare names the gate is told about. Reads, all of them: they take RemodelGuard's
    // delegation branch to ReadOnlyGuard exactly as the reviewer's reads do, which is what
    // keeps the stage-1 allowlist the whole of the write surface.
    private const string BodiesMember = "GetBodies2";
    private const string FaceCountMember = "GetFaceCount";
    private const string EdgeCountMember = "GetEdgeCount";
    private const string MaterialMember = "GetMaterialPropertyName2";
    private const string CreateMember = "CreateMassProperty2";
    private const string UseSystemUnitsMember = "set_UseSystemUnits";
    private const string RecalculateMember = "Recalculate";
    private const string VolumeMember = "get_Volume";
    private const string SurfaceAreaMember = "get_SurfaceArea";
    private const string CenterOfMassMember = "get_CenterOfMass";
    private const string PrincipalMomentsMember = "get_PrincipalMomentsOfInertia";
    private const string MassMember = "get_Mass";
    private const string DensityMember = "get_Density";

    /// <summary>
    /// One reading of <paramref name="document"/>, which is always the run's own copy: the
    /// scope holds the only <c>IModelDoc2</c> a remodel command can reach, and this command
    /// takes no parameters because there is nothing for a caller to name.
    /// </summary>
    /// <param name="subject">
    /// <c>copy_at_open</c> or <c>copy_at_end</c>, stamped by the run's own phase
    /// (<see cref="RemodelGeometrySubjects"/>), never asked for by the caller.
    /// </param>
    /// <param name="sourceSha256">
    /// The attested hash of the file the copy was made from, so the artifact says on its face
    /// which file the baseline stands for (FR-037). The source is never opened.
    /// </param>
    /// <param name="stage">Where each call's markers go, or null for none.</param>
    public static GeometryReading Read(
        SwGate gate,
        IRemodelDocument document,
        string subject,
        string sourceSha256,
        DateTime at,
        Action<string>? stage = null)
    {
        if (gate == null)
        {
            throw new ArgumentNullException(nameof(gate));
        }

        if (document == null)
        {
            throw new ArgumentNullException(nameof(document));
        }

        IReadOnlyList<object> solids = Bodies(gate, document, SolidBody, stage);
        IReadOnlyList<object> sheets = Bodies(gate, document, SheetBody, stage);

        var reading = new GeometryReading
        {
            At = at,
            Subject = subject,
            SourceSha256 = sourceSha256,

            // Null: this reading sets no accuracy of its own, so SOLIDWORKS's default applies.
            AccuracyLevel = null,
            SolidBodyCount = solids.Count,
            SheetBodyCount = sheets.Count,

            // Read whatever the mass properties do: the material is not geometry, and a
            // mass-only difference is reported as a material change and never as a moved part.
            MaterialName = Call(gate, MaterialMember, document.GetMaterialName, stage),
        };

        if (solids.Count == 0)
        {
            // Nothing to select, so no mass property is built at all. Reported, not defaulted:
            // a zero volume here would be a number the gate could compare.
            reading.Status = StatusNoBody;
            return reading;
        }

        reading.FaceCount = Sum(gate, document, solids, FaceCountMember, isFaces: true, stage: stage);
        reading.EdgeCount = Sum(gate, document, solids, EdgeCountMember, isFaces: false, stage: stage);

        if (solids.Count != 1)
        {
            // A whole-part reading of two bodies measures both at once, and no pairing can
            // compare it; the scope gate refuses such a part, so this is a change that split one.
            // Counted and reported, never measured.
            reading.Status = StatusUnknownError;
            return reading;
        }

        IMassPropertyReading? properties = Call(gate, CreateMember, document.CreateMassProperty, stage);
        if (properties == null)
        {
            reading.Status = StatusUnknownError;
            return reading;
        }

        // Before Recalculate, never after: the numbers are computed in whatever units are in
        // force when it runs, and this record's fields are named for metres and kilograms.
        Call(gate, UseSystemUnitsMember, () => properties.SetUseSystemUnits(true), stage);

        reading.Recalculated = Call(gate, RecalculateMember, properties.Recalculate, stage);
        if (!reading.Recalculated)
        {
            // Nothing is read: the values still in there are the previous body's.
            reading.Status = StatusUnknownError;
            return reading;
        }

        double volume = Call(gate, VolumeMember, properties.GetVolume, stage);
        if (!(volume > 0) || double.IsInfinity(volume))
        {
            // Not a solid's volume (zero, negative, NaN or infinite): nothing else is read, and
            // nothing is recorded that the gate could compare.
            reading.Status = StatusUnknownError;
            return reading;
        }

        reading.Status = StatusOk;
        reading.VolumeM3 = volume;
        reading.SurfaceAreaM2 = Call(gate, SurfaceAreaMember, properties.GetSurfaceArea, stage);
        reading.CenterOfMassM = Triple3(
            Call(gate, CenterOfMassMember, properties.GetCenterOfMass, stage), sorted: false);
        reading.PrincipalMoments = Triple3(
            Call(gate, PrincipalMomentsMember, properties.GetPrincipalMomentsOfInertia, stage),
            sorted: true);
        reading.MassKg = Call(gate, MassMember, properties.GetMass, stage);
        reading.Density = Call(gate, DensityMember, properties.GetDensity, stage);

        return reading;
    }

    private static IReadOnlyList<object> Bodies(
        SwGate gate, IRemodelDocument document, int bodyType, Action<string>? stage)
    {
        // Body type disambiguates two consecutive calls with the same interop member.
        IReadOnlyList<object>? bodies = Call(
            gate, BodiesMember, () => document.GetBodies(bodyType), stage,
            bodyType == SolidBody ? "solid" : "sheet");

        // GetBodies2 answers null for a part with no body of that type; that is a count of
        // zero and not an unreadable one.
        return bodies ?? (IReadOnlyList<object>)new object[0];
    }

    /// <summary>
    /// The faces or edges of every solid body. One body that will not answer makes the whole
    /// count unknown: a sum missing a body is a smaller number, not a missing one, and the gate
    /// compares face counts exactly.
    /// </summary>
    private static int? Sum(
        SwGate gate,
        IRemodelDocument document,
        IReadOnlyList<object> bodies,
        string member,
        bool isFaces,
        Action<string>? stage)
    {
        int total = 0;
        foreach (object body in bodies)
        {
            object one = body;
            int? count = Call(
                gate,
                member,
                () => isFaces ? document.GetFaceCount(one) : document.GetEdgeCount(one),
                stage);

            if (count == null)
            {
                return null;
            }

            total += count.Value;
        }

        return total;
    }

    private static T Call<T>(
        SwGate gate, string member, Func<T> read, Action<string>? stage, string? detail = null) =>
        RemodelStageMarkers.Around(
            stage, detail == null ? member : member + ":" + detail, () => gate.Call(member, read));

    private static void Call(
        SwGate gate, string member, Action read, Action<string>? stage)
    {
        Call<object?>(gate, member, () => { read(); return null; }, stage);
    }

    /// <summary>
    /// Three values or nothing. <paramref name="sorted"/> is the principal moments' rule: they
    /// are sorted ascending before anything compares them, because a symmetry-degenerate
    /// rotation returns the same three numbers permuted.
    /// </summary>
    private static IReadOnlyList<double>? Triple3(IReadOnlyList<double>? values, bool sorted)
    {
        if (values == null || values.Count != Triple)
        {
            return null;
        }

        var triple = new double[Triple];
        for (int index = 0; index < Triple; index++)
        {
            triple[index] = values[index];
        }

        if (sorted)
        {
            Array.Sort(triple);
        }

        return triple;
    }
}
