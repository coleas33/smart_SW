namespace SwReview.Extractor.Ir;

// Every enum below mirrors an `enum` list in contracts/ir.schema.json.
// Member names are PascalCase; SnakeCaseLowerNamingPolicy in PackageSerializer converts
// them to the exact strings the schema allows (AntiAligned -> "anti_aligned", Mm3 -> "mm3").
// Adding a member here without adding it to the schema breaks IrSerializerTests.

/// <summary>Quantity.unit: "mm" | "in" | "m".</summary>
public enum LengthUnit
{
    Mm,
    In,
    M,
}

/// <summary>Angle.unit: "deg" | "rad".</summary>
public enum AngleUnit
{
    Deg,
    Rad,
}

/// <summary>Volume.unit: "mm3" | "in3" | "m3".</summary>
public enum VolumeUnit
{
    Mm3,
    In3,
    M3,
}

/// <summary>Tolerance.kind. "None" means no tolerance was found; checks treat it as unknown.</summary>
public enum ToleranceKind
{
    Symmetric,
    Bilateral,
    Limits,
    Basic,
    None,
}

/// <summary>ManifestEntry.export_method.</summary>
public enum ExportMethod
{
    Native,
    Pdf,
    Step,
    Manual,
}

/// <summary>Discrepancy.kind.</summary>
public enum DiscrepancyKind
{
    VersionMismatch,
    LocalModification,
    MissingDocument,
    ConfigMismatch,
}

/// <summary>Document.kind.</summary>
public enum DocumentKind
{
    Part,
    Assembly,
    Drawing,
}

/// <summary>
/// ComponentInstance.suppression. Mapped from swComponentSuppressionState_e by the dumper
/// (research R12): 0 suppressed, 1 and 4 lightweight, 2 and 3 resolved, 5 unloaded + Gap.
/// </summary>
public enum SuppressionState
{
    Resolved,
    Lightweight,
    Suppressed,
    Unloaded,
}

/// <summary>Mate.alignment.</summary>
public enum MateAlignment
{
    Aligned,
    AntiAligned,
    Closest,
}

/// <summary>Hole.hole_type.</summary>
public enum HoleType
{
    Tapped,
    Clearance,
    Counterbore,
    Countersink,
    Simple,
    Unknown,
}

/// <summary>Hole.end_condition.</summary>
public enum EndCondition
{
    Blind,
    Through,
    Unknown,
}

/// <summary>Fastener.kind.</summary>
public enum FastenerKind
{
    Screw,
    Bolt,
    Nut,
    Washer,
    Pin,
    Other,
}

/// <summary>
/// Fastener.identity_source, in descending confidence. NameParse results are reported as
/// "suspected", never "demonstrated" (data-model.md section 2).
/// </summary>
public enum IdentitySource
{
    Toolbox,
    CustomProperty,
    NameParse,
    Manual,
}

/// <summary>FaceGeometry.kind.</summary>
public enum FaceKind
{
    Cylinder,
    Plane,
    Cone,
    Torus,
    Other,
}

/// <summary>Interference.status.</summary>
public enum InterferenceStatus
{
    Computed,
    Truncated,
    Failed,
}

/// <summary>Interference.settings.fastener_folder_treatment.</summary>
public enum FastenerFolderTreatment
{
    Include,
    Exclude,
    Only,
}

/// <summary>Note.kind.</summary>
public enum NoteKind
{
    GeneralTolerance,
    Material,
    Finish,
    Other,
}

/// <summary>
/// MateEntity.resolution_status (schema 1.4.0): what <c>IMateEntity2.Reference</c> said about
/// one mate entity, with no new interop call. Before it, a reference that came back null and
/// a read that threw were both a null persist_ref and neither could be told from the other -
/// which is the whole defect standards.assembly.mate_references hunts.
/// </summary>
public enum MateEntityResolution
{
    /// <summary>The reference was non-null.</summary>
    Resolved,

    /// <summary>The reference was null: the mate points at an entity that is gone.</summary>
    Unresolved,

    /// <summary>The read threw; a mate_entity_reference gap says so.</summary>
    Unknown,
}

/// <summary>
/// Which path produced a drawing sheet (schema 1.4.0): the native <c>drawing</c> dump phase or
/// the Python PDF ingest. Carried per sheet, so a drawing whose sheets came from both has a
/// per-sheet answer (FR-024). Null on a <see cref="DrawingSheet"/> written before the stamp
/// existed, which the drawing checks treat exactly as <see cref="PdfIngest"/>.
/// </summary>
public enum DrawingEvidenceSource
{
    Native,
    PdfIngest,
}

/// <summary>DrawingSheet.units: "mm" | "in" | "unknown".</summary>
public enum SheetUnits
{
    Mm,
    In,
    Unknown,
}

/// <summary>DrawingSheet.parse_status.</summary>
public enum ParseStatus
{
    Text,
    NoText,
    Failed,
}

/// <summary>Gap.kind. Every gap becomes an unresolved coverage item in the review.</summary>
public enum GapKind
{
    NotExtracted,
    Unsupported,
    ToolError,
    NoText,
}

/// <summary>
/// DumpPhase.status (feature 005 T033): what became of one phase of the dump.
///
/// Four outcomes, because the three ways a phase can end and the one way it can never
/// start are different facts about the package beside them: an empty <c>holes[]</c> under
/// <see cref="Ok"/> is a part with no holes, under <see cref="Failed"/> it is evidence the
/// dump lost, and under <see cref="Skipped"/> it is a phase nobody ran.
/// </summary>
public enum DumpPhaseStatus
{
    /// <summary>It ran and returned.</summary>
    Ok,

    /// <summary>It threw; the failure is a gap and the dump carried on.</summary>
    Failed,

    /// <summary>SOLIDWORKS stopped answering inside it, and the phases behind it were skipped.</summary>
    Aborted,

    /// <summary>
    /// It was never run: switched off by the profile or the options, or behind a phase that
    /// aborted. Its <c>elapsed_ms</c> is null - a phase that never ran has no elapsed time,
    /// and 0 would read as one that ran and cost nothing.
    /// </summary>
    Skipped,
}

/// <summary>SuppressTestRow.outcome (schema 1.1.0).</summary>
public enum SuppressTestOutcome
{
    /// <summary>Suppressed, rebuilt, and no new rebuild error above the baseline.</summary>
    Ok,

    /// <summary>The rebuild reported more wrong than the baseline did.</summary>
    RebuildErrors,

    /// <summary>The feature was already suppressed before the run, so nothing was proved.</summary>
    AlreadySuppressed,

    /// <summary>The suppression did not take effect.</summary>
    NotApplied,

    /// <summary>Beyond --limit; planned but never attempted.</summary>
    Truncated,

    /// <summary>The run stopped before this feature finished.</summary>
    Aborted,
}

/// <summary>ModelDimension.dimension_type (schema 1.5.0, feature 010).</summary>
public enum ModelDimensionType
{
    Linear,
    Diameter,
    Radius,
    Angular,

    /// <summary>A type none of the four names; <c>dimension_type_raw</c> keeps the number.</summary>
    Other,
}

/// <summary>AttachedFace.via (schema 1.6.0, feature 011).</summary>
public enum AttachedVia
{
    /// <summary>The annotation was attached to this face.</summary>
    Face,

    /// <summary>The annotation was attached to an edge; this is one of its two adjacent faces.</summary>
    Edge,
}

/// <summary>DrawingCandidate.reason (schema 1.6.0, feature 011): the only rule.</summary>
public enum DrawingCandidateReason
{
    /// <summary>Same folder, same file stem, .SLDDRW, beside a reviewed document.</summary>
    SameNameBesideModel,
}

/// <summary>ModelAnnotation.kind (schema 1.5.0, feature 010).</summary>
public enum ModelAnnotationKind
{
    /// <summary>An IGtol: a geometric tolerance frame.</summary>
    Gtol,

    /// <summary>An IDatumTag.</summary>
    Datum,
}
