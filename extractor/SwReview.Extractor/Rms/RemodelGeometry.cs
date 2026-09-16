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
    /// <summary><c>IMassProperty2.set_AccuracyLevel</c>; always <c>Higher = 2</c>.</summary>
    void SetAccuracyLevel(int accuracyLevel);

    /// <summary><c>IMassProperty2.set_SelectedItems</c>: the solid bodies, and nothing else.</summary>
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
/// Three rules the shape encodes, each with its own test:
///
///   * <b><c>Recalculate()</c> first.</b> Its Boolean is checked before any value is read, and
///     a false answer ends the reading with every measured field null.
///   * <b>The principal moments are sorted ascending</b>, because two bodies differing by a
///     symmetry-degenerate rotation return the same three numbers permuted, and a comparison of
///     unsorted triples would call them different.
///   * <b>A status other than <c>OK</c> is reported.</b> Unknown stays unknown: a defaulted zero
///     volume is a number the gate would compare and pass.
/// </summary>
public static class RemodelGeometry
{
    /// <summary><c>swMassPropertyAccuracyLevel_e.swMassPropertyAccuracyLevel_Higher</c> (VERIFIED value 2).</summary>
    public const int HigherAccuracy =
        (int)swMassPropertyAccuracyLevel_e.swMassPropertyAccuracyLevel_Higher;

    /// <summary><c>swMassPropertiesStatus_e.swMassPropertiesStatus_OK</c> (VERIFIED value 0).</summary>
    public const int StatusOk = (int)swMassPropertiesStatus_e.swMassPropertiesStatus_OK;

    /// <summary>
    /// <c>swMassPropertiesStatus_e.swMassPropertiesStatus_UnknownError</c> (VERIFIED value 1):
    /// the mass property could not be built, or <c>Recalculate()</c> answered false. The typed
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
    private const string AccuracyMember = "set_AccuracyLevel";
    private const string SelectedItemsMember = "set_SelectedItems";
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
    public static GeometryReading Read(
        SwGate gate,
        IRemodelDocument document,
        string subject,
        string sourceSha256,
        DateTime at)
    {
        if (gate == null)
        {
            throw new ArgumentNullException(nameof(gate));
        }

        if (document == null)
        {
            throw new ArgumentNullException(nameof(document));
        }

        IReadOnlyList<object> solids = Bodies(gate, document, SolidBody);
        IReadOnlyList<object> sheets = Bodies(gate, document, SheetBody);

        var reading = new GeometryReading
        {
            At = at,
            Subject = subject,
            SourceSha256 = sourceSha256,
            AccuracyLevel = HigherAccuracy,
            SolidBodyCount = solids.Count,
            SheetBodyCount = sheets.Count,

            // Read whatever the mass properties do: the material is not geometry, and a
            // mass-only difference is reported as a material change and never as a moved part.
            MaterialName = gate.Call(MaterialMember, document.GetMaterialName),
        };

        if (solids.Count == 0)
        {
            // Nothing to select, so no mass property is built at all. Reported, not defaulted:
            // a zero volume here would be a number the gate could compare.
            reading.Status = StatusNoBody;
            return reading;
        }

        reading.FaceCount = Sum(gate, document, solids, FaceCountMember, isFaces: true);
        reading.EdgeCount = Sum(gate, document, solids, EdgeCountMember, isFaces: false);

        IMassPropertyReading? properties = gate.Call(CreateMember, document.CreateMassProperty);
        if (properties == null)
        {
            reading.Status = StatusUnknownError;
            return reading;
        }

        gate.Call(AccuracyMember, () => properties.SetAccuracyLevel(HigherAccuracy));
        gate.Call(SelectedItemsMember, () => properties.SetSelectedItems(solids));

        // Before Recalculate, never after: the numbers are computed in whatever units are in
        // force when it runs, and this record's fields are named for metres and kilograms.
        gate.Call(UseSystemUnitsMember, () => properties.SetUseSystemUnits(true));

        reading.Recalculated = gate.Call(RecalculateMember, properties.Recalculate);
        if (!reading.Recalculated)
        {
            // Nothing is read: the values still in there are the previous body's.
            reading.Status = StatusUnknownError;
            return reading;
        }

        reading.Status = StatusOk;
        reading.VolumeM3 = gate.Call(VolumeMember, properties.GetVolume);
        reading.SurfaceAreaM2 = gate.Call(SurfaceAreaMember, properties.GetSurfaceArea);
        reading.CenterOfMassM = Triple3(
            gate.Call(CenterOfMassMember, properties.GetCenterOfMass), sorted: false);
        reading.PrincipalMoments = Triple3(
            gate.Call(PrincipalMomentsMember, properties.GetPrincipalMomentsOfInertia),
            sorted: true);
        reading.MassKg = gate.Call(MassMember, properties.GetMass);
        reading.Density = gate.Call(DensityMember, properties.GetDensity);

        return reading;
    }

    private static IReadOnlyList<object> Bodies(SwGate gate, IRemodelDocument document, int bodyType)
    {
        IReadOnlyList<object>? bodies = gate.Call(
            BodiesMember, () => document.GetBodies(bodyType));

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
        bool isFaces)
    {
        int total = 0;
        foreach (object body in bodies)
        {
            object one = body;
            int? count = gate.Call(
                member,
                () => isFaces ? document.GetFaceCount(one) : document.GetEdgeCount(one));

            if (count == null)
            {
                return null;
            }

            total += count.Value;
        }

        return total;
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
