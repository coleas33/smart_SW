using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Probes;

/// <summary>
/// Feature 011 T081 (contracts/probes.md section 2): runs the selected drawing probes over a
/// <see cref="DrawingProbeContext"/> and returns their sections, each opening with its id, its title
/// and what it runs on.
///
/// The drawing sections print what the <b>shipped extraction</b> read - one Standards extraction of
/// the open drawing, the Standards tab's own options, shared by every section - so the seat validates
/// the reads the product makes rather than a copy of them. D5, D6 and D8 compare it with each shown
/// part's own Full extraction, taken only of a part SOLIDWORKS already has open. D2, D3, D7, D10 and
/// D11 add the few reads the extraction does not record, D13 times the candidate check, and D14 runs
/// the confirmed open's own seam (<see cref="DrawingOpenProbe"/>).
///
/// Every line is ids, counts, member answers, enum numbers and millimetres (<see cref="ProbeText"/>);
/// a read that fails is printed and the run carries on; nothing is opened except by D14.
/// </summary>
public static class DrawingProbeRunner
{
    /// <summary>The most part documents D5, D6 and D8 extract for their comparison; the rest are counted.</summary>
    public const int MaxModelReadings = 5;

    /// <summary><c>swUserPreferenceIntegerValue_e.swDetailingDimensionStandard</c>, the one preference D11 reads itself.</summary>
    private const int DimensionStandardPreference = 13;

    private const string AttachmentGap = "drawing_attachment";

    /// <summary>
    /// The Standards tab's extraction of a drawing (<c>SwReviewDump</c>, 006 FR-025): the
    /// <c>standards</c> profile, faces as needed, and no meshes, since nothing is written.
    /// </summary>
    public static DumpOptions StandardsOptions() =>
        new DumpOptions { Profile = DumpProfile.Standards, Meshes = MeshFormat.None, Faces = FaceScope.Needed };

    /// <summary>
    /// A part's own extraction for D5, D6 and D8: the review's (<c>full</c>: its tolerance phase and
    /// the faces its holes name), with no meshes, since nothing is written.
    /// </summary>
    public static DumpOptions ModelOptions() =>
        new DumpOptions { Profile = DumpProfile.Full, Meshes = MeshFormat.None, Faces = FaceScope.Needed };

    /// <summary>The sections of <paramref name="ids"/>, in catalog order, once each.</summary>
    public static IReadOnlyList<string> Run(IReadOnlyList<string> ids, DrawingProbeContext context)
    {
        if (context == null)
        {
            throw new ArgumentNullException(nameof(context));
        }

        IReadOnlyList<string> selected = DrawingProbeCatalog.InCatalogOrder(ids ?? Array.Empty<string>());
        var run = new ProbeRun(context, selected);
        var lines = new List<string>();
        foreach (string id in selected)
        {
            DrawingProbeDefinition probe = DrawingProbeCatalog.Get(id);
            lines.Add($"{probe.Id}: {probe.Title}");
            lines.Add($"  run on: {probe.RunOn}");
            if (!probe.AppliesTo(context.Kind))
            {
                lines.Add($"  does not apply to a {PackageSerializer.EnumToJsonName(context.Kind)}, so nothing was read");
                continue;
            }

            try
            {
                lines.AddRange(run.Section(id));
            }
            catch (Exception error)
            {
                lines.Add("  stopped: " + ProbeText.Failure(error));
            }
        }

        return lines;
    }

    /// <summary>One run: the extractions every section shares, taken once and remembered, failures included.</summary>
    private sealed class ProbeRun
    {
        private static readonly Regex DefaultDimensionName = new Regex("^R?D[0-9]+$", RegexOptions.CultureInvariant);

        private readonly DrawingProbeContext _context;
        private readonly ProbeAnswer<string?>? _activeSheetBefore;
        private PackageReading? _standards;
        private ModelReadings? _models;

        public ProbeRun(DrawingProbeContext context, IReadOnlyList<string> selected)
        {
            _context = context;

            // D3's "before" is read before anything else the run does, the extraction included.
            if (context.Kind == DocumentKind.Drawing && selected.Contains("D3"))
            {
                _activeSheetBefore = ProbeAnswer<string?>.Of(() => context.Reads.ActiveSheetName(context.Document));
            }
        }

        public IReadOnlyList<string> Section(string id)
        {
            switch (id)
            {
                case "D1": return D1();
                case "D2": return D2();
                case "D3": return D3();
                case "D4": return D4();
                case "D5": return D5();
                case "D6": return D6();
                case "D7": return D7();
                case "D8": return D8();
                case "D9": return D9();
                case "D10": return D10();
                case "D11": return D11();
                case "D12": return D12();
                case "D13": return D13();
                case "D14": return DrawingOpenProbe.Run(_context.DocumentPath, _context.OpenSeam, _context.Files);
                default: throw new ArgumentException($"'{id}' is not a drawing probe.", nameof(id));
            }
        }

        // ---- D1 --------------------------------------------------------------------------------

        private IReadOnlyList<string> D1()
        {
            PackageReading reading = Standards();
            if (reading.Package == null)
            {
                return new[] { $"  stopped after {reading.ElapsedMs} ms: {reading.Failure}" };
            }

            EvidencePackage package = reading.Package;
            var lines = new List<string> { $"  completed in {reading.ElapsedMs} ms" };

            List<DumpPhase> phases = package.Extractor.Phases;
            lines.Add("  phases: " + (phases.Count == 0
                ? "none recorded"
                : string.Join(", ", phases.Select(phase =>
                    $"{phase.Name} {PackageSerializer.EnumToJsonName(phase.Status)}"
                    + (phase.ElapsedMs == null ? string.Empty : $" {phase.ElapsedMs} ms")))));

            List<DrawingRecord> records = package.DrawingRecords ?? new List<DrawingRecord>();
            List<DrawingSheetRecord> sheets = records.SelectMany(record => record.Sheets).ToList();
            lines.Add(records.Count == 0
                ? "  drawing records 0"
                : $"  drawing records {records.Count}, sheets {sheets.Count}, views {sheets.Sum(sheet => sheet.Views.Count)} "
                    + $"(by sheet: {string.Join(", ", sheets.Select(sheet => sheet.Views.Count))})");

            List<string> kinds = package.Gaps
                .GroupBy(gap => PackageSerializer.EnumToJsonName(gap.Kind) + "/" + gap.EntityKind, StringComparer.Ordinal)
                .OrderBy(group => group.Key, StringComparer.Ordinal)
                .Select(group => $"{group.Key} {group.Count()}")
                .ToList();
            lines.Add(kinds.Count == 0 ? "  gaps 0" : $"  gaps {package.Gaps.Count}: {string.Join(", ", kinds)}");
            return lines;
        }

        // ---- D2 --------------------------------------------------------------------------------

        private IReadOnlyList<string> D2()
        {
            ProbeAnswer<IReadOnlyList<OpenDocument>> listing =
                ProbeAnswer<IReadOnlyList<OpenDocument>>.Of(() => _context.OpenDocuments.OpenDocuments());
            if (!listing.Answered)
            {
                return new[] { $"  GetDocuments failed: {listing.Failure}" };
            }

            IReadOnlyList<OpenDocument> documents = listing.Value;
            var lines = new List<string> { $"  documents listed {documents.Count}" };
            var positionsByPath = new Dictionary<string, List<int>>(StringComparer.OrdinalIgnoreCase);

            for (int i = 0; i < documents.Count; i++)
            {
                OpenDocument document = documents[i];
                ProbeAnswer<DocumentKind> kind = ProbeAnswer<DocumentKind>.Of(document.ReadKind);
                ProbeAnswer<string?> path = ProbeAnswer<string?>.Of(document.ReadPath);
                ProbeAnswer<bool> visible = ProbeAnswer<bool>.Of(() => _context.Reads.Visible(
                    document.Handle ?? throw new InvalidOperationException("The listing gave no document handle.")));

                string line = $"  {i + 1}: "
                    + (kind.Answered ? PackageSerializer.EnumToJsonName(kind.Value) : $"kind {ProbeText.Unread} ({kind.Failure})")
                    + ", visible " + visible.Print(ProbeText.Bool);
                if (kind.Answered && kind.Value == DocumentKind.Drawing)
                {
                    ProbeAnswer<IReadOnlyList<string>> views = ProbeAnswer<IReadOnlyList<string>>.Of(document.ReadReferencedPaths);
                    line += views.Answered
                        ? $", views {views.Value.Count} (blank {views.Value.Count(string.IsNullOrWhiteSpace)}), "
                            + $"referenced documents {views.Value.Select(OpenDrawingDiscovery.Key).Where(key => key != null).Distinct(StringComparer.OrdinalIgnoreCase).Count()}"
                        : $", views {ProbeText.Unread} ({views.Failure})";
                }

                if (!path.Answered)
                {
                    line += $", path {ProbeText.Unread} ({path.Failure})";
                }
                else if (OpenDrawingDiscovery.Key(path.Value) is string key)
                {
                    if (!positionsByPath.TryGetValue(key, out List<int>? positions))
                    {
                        positions = new List<int>();
                        positionsByPath[key] = positions;
                    }

                    positions.Add(i + 1);
                }

                lines.Add(line);
            }

            List<string> twice = positionsByPath.Values
                .Where(positions => positions.Count > 1)
                .OrderBy(positions => positions[0])
                .Select(positions => ProbeText.And(positions.Select(p => p.ToString(CultureInfo.InvariantCulture)).ToList()))
                .ToList();
            lines.Add("  listed twice: " + (twice.Count == 0 ? "none" : string.Join("; ", twice)));
            return lines;
        }

        // ---- D3 --------------------------------------------------------------------------------

        private IReadOnlyList<string> D3()
        {
            var lines = new List<string>();
            if (!TryRecord(lines, out DrawingRecord record))
            {
                return lines;
            }

            ProbeAnswer<string?> before = _activeSheetBefore ?? ProbeAnswer<string?>.Of(() => null);
            ProbeAnswer<string?> after = ProbeAnswer<string?>.Of(() => _context.Reads.ActiveSheetName(_context.Document));
            string unchanged = before.Answered && after.Answered
                ? ProbeText.Bool(string.Equals(before.Value, after.Value, StringComparison.Ordinal))
                : ProbeText.Unread;
            lines.Add($"  active sheet: {SheetPosition(record, before, "position ")} before the run, "
                + $"{SheetPosition(record, after, string.Empty)} after, unchanged {unchanged}; "
                + $"the extraction read {SheetPosition(record, ProbeAnswer<string?>.Of(() => record.ActiveSheetName), "position ")} as active");

            ProbeAnswer<IReadOnlyList<IReadOnlyList<int>>> fromDocument =
                ProbeAnswer<IReadOnlyList<IReadOnlyList<int>>>.Of(() => _context.Reads.DocumentViewTypes(_context.Document));
            if (!fromDocument.Answered)
            {
                lines.Add($"  IDrawingDoc.GetViews failed: {fromDocument.Failure}");
            }

            int documentSheets = fromDocument.Answered ? fromDocument.Value.Count : 0;
            int readSheets = record.Sheets.Count == 0 ? 0 : record.Sheets.Max(sheet => sheet.Index) + 1;
            for (int i = 0; i < Math.Max(documentSheets, readSheets); i++)
            {
                string documentViews = !fromDocument.Answered
                    ? ProbeText.Unread
                    : i < documentSheets
                        ? Views(fromDocument.Value[i].Select(type => (int?)type).ToList())
                        : "not returned";
                DrawingSheetRecord? sheet = record.Sheets.FirstOrDefault(row => row.Index == i);
                string sheetViews = sheet == null ? "not read" : Views(sheet.Views.Select(view => view.ViewTypeRaw).ToList());
                lines.Add($"  sheet {i + 1}: IDrawingDoc.GetViews {documentViews}; ISheet.GetViews {sheetViews}");
            }

            return lines;
        }

        private static string SheetPosition(DrawingRecord record, ProbeAnswer<string?> name, string prefix)
        {
            if (!name.Answered)
            {
                return $"{ProbeText.Unread} ({name.Failure})";
            }

            if (name.Value == null)
            {
                return ProbeText.Unread;
            }

            DrawingSheetRecord? sheet = record.Sheets.FirstOrDefault(
                row => string.Equals(row.Name, name.Value, StringComparison.Ordinal));
            return sheet == null ? "not among the sheets read" : prefix + (sheet.Index + 1).ToString(CultureInfo.InvariantCulture);
        }

        private static string Views(IReadOnlyList<int?> types) =>
            types.Count == 0
                ? "no views"
                : $"{ProbeText.Count(types.Count, "view")}, {(types.Count == 1 ? "type" : "types")} "
                    + string.Join(", ", types.Select(ProbeText.Int));

        // ---- D4 --------------------------------------------------------------------------------

        private IReadOnlyList<string> D4()
        {
            var lines = new List<string>();
            if (!TryRecord(lines, out DrawingRecord record))
            {
                return lines;
            }

            lines.Add($"  document: 24 (swDetailingLinearDimPrecision) {ProbeText.Int(record.DimensionPrecisionRaw)}, "
                + $"25 (swDetailingLinearTolPrecision) {ProbeText.Int(record.TolerancePrecisionRaw)}, "
                + $"47 (swUnitsLinear) {ProbeText.Int(record.LengthUnitRaw)}, "
                + $"49 (swUnitsLinearDecimalPlaces) {ProbeText.Int(record.UnitsDecimalPlacesRaw)}");

            int before = lines.Count;
            foreach ((DrawingSheetRecord sheet, DrawingView view) in ViewsOf(record))
            {
                foreach (DisplayDimensionRecord dimension in view.DisplayDimensions)
                {
                    lines.Add($"  {dimension.Id} {Where(sheet, view)}: "
                        + $"GetPrimaryPrecision2 {ProbeText.Int(dimension.PrecisionRaw)}, "
                        + $"GetPrimaryTolPrecision2 {ProbeText.Int(dimension.TolerancePrecisionRaw)}, "
                        + $"GetUseDocPrecision {ProbeText.Bool(dimension.UsesDocumentPrecision)}, "
                        + $"GetUnits {ProbeText.Int(dimension.UnitsRaw)}, "
                        + $"GetUseDocUnits {ProbeText.Bool(dimension.UsesDocumentUnits)}");
                }
            }

            if (lines.Count == before)
            {
                lines.Add("  no display dimension was read");
            }

            return lines;
        }

        // ---- D5 --------------------------------------------------------------------------------

        private IReadOnlyList<string> D5()
        {
            var lines = new List<string>();
            if (!TryRecord(lines, out DrawingRecord record))
            {
                return lines;
            }

            ModelReadings models = Models(record);
            lines.AddRange(models.Lines);

            foreach ((DrawingSheetRecord sheet, DrawingView view) in ViewsOf(record))
            {
                foreach (DisplayDimensionRecord dimension in view.DisplayDimensions)
                {
                    lines.Add($"  {dimension.Id} {Where(sheet, view)}: "
                        + ToleranceText(dimension.ToleranceTypeRaw, dimension.Tolerance, dimension.FitHoleClass, dimension.FitShaftClass)
                        + $"; reference {ProbeText.Bool(dimension.IsReference)}, driven state {ProbeText.Int(dimension.DrivenStateRaw)}");
                    lines.Add(PartLine(models, view, dimension, match =>
                        $"    the part: {match.Id} "
                        + ToleranceText(match.ToleranceTypeRaw, match.Tolerance, match.FitHoleClass, match.FitShaftClass)
                        + $"; agree {ProbeText.Bool(SameTolerance(dimension, match))}"));
                }
            }

            return lines;
        }

        private static string ToleranceText(int? typeRaw, Tolerance? tolerance, string? hole, string? shaft) =>
            $"Tolerance.Type {ProbeText.Int(typeRaw)}, "
            + (tolerance == null ? ProbeText.Unread : PackageSerializer.EnumToJsonName(tolerance.Kind))
            + $", upper {ProbeText.Limit(tolerance?.Upper)}, lower {ProbeText.Limit(tolerance?.Lower)}, fit {Fit(hole, shaft)}";

        private static string Fit(string? hole, string? shaft) =>
            hole == null && shaft == null ? "none" : $"{hole ?? "-"}/{shaft ?? "-"}";

        private static bool SameTolerance(DisplayDimensionRecord drawing, ModelDimension model) =>
            drawing.ToleranceTypeRaw == model.ToleranceTypeRaw
            && (drawing.Tolerance == null
                ? model.Tolerance == null
                : model.Tolerance != null && drawing.Tolerance.Kind == model.Tolerance.Kind)
            && ProbeText.SameMeasure(drawing.Tolerance?.Upper, model.Tolerance?.Upper)
            && ProbeText.SameMeasure(drawing.Tolerance?.Lower, model.Tolerance?.Lower)
            && string.Equals(drawing.FitHoleClass, model.FitHoleClass, StringComparison.Ordinal)
            && string.Equals(drawing.FitShaftClass, model.FitShaftClass, StringComparison.Ordinal);

        /// <summary>
        /// The part's line for one drawing dimension: its one model dimension of the same
        /// <c>dimension@feature</c> printed by <paramref name="print"/>, or why there is none.
        /// </summary>
        private static string PartLine(
            ModelReadings models, DrawingView view, DisplayDimensionRecord dimension, Func<ModelDimension, string> print)
        {
            if (string.IsNullOrWhiteSpace(dimension.Name))
            {
                return "    the part: not compared (the dimension's name was not read)";
            }

            List<ModelReading> relevant = models.Readings
                .Where(reading => view.ReferencedDocumentId == null
                    || !models.Readings.Any(r => r.DocumentId == view.ReferencedDocumentId)
                    || reading.DocumentId == view.ReferencedDocumentId)
                .ToList();
            List<ModelReading> read = relevant.Where(reading => reading.Package != null).ToList();
            if (read.Count == 0)
            {
                return "    the part: not read";
            }

            string core = DimensionAndFeature(dimension.Name!);
            List<ModelDimension> matches = read
                .SelectMany(reading => (reading.Package!.ModelDimensions ?? new List<ModelDimension>())
                    .Where(model => string.Equals(model.DocumentId, reading.DocumentId, StringComparison.Ordinal)))
                .Where(model => string.Equals(DimensionAndFeature(model.Name), core, StringComparison.OrdinalIgnoreCase))
                .ToList();

            switch (matches.Count)
            {
                case 0:
                    return "    the part: no model dimension with the same dimension@feature";
                case 1:
                    return print(matches[0]);
                default:
                    return $"    the part: {matches.Count} model dimensions with the same dimension@feature "
                        + $"({string.Join(", ", matches.Select(match => match.Id))})";
            }
        }

        /// <summary>The first two segments of a full name - the dimension and its feature - or the whole name when it has fewer.</summary>
        private static string DimensionAndFeature(string fullName)
        {
            string[] segments = (fullName ?? string.Empty).Split('@');
            return segments.Length >= 2 ? segments[0] + "@" + segments[1] : fullName ?? string.Empty;
        }

        // ---- D6 --------------------------------------------------------------------------------

        private IReadOnlyList<string> D6()
        {
            var lines = new List<string>();
            if (!TryRecord(lines, out DrawingRecord record))
            {
                return lines;
            }

            ModelReadings models = Models(record);
            lines.AddRange(models.Lines);
            List<Gap> gaps = Standards().Package!.Gaps;

            int owners = 0;
            foreach ((DrawingSheetRecord sheet, DrawingView view) in ViewsOf(record))
            {
                var attached = view.DisplayDimensions
                    .Select(dimension => (dimension.Id, What: "dimension", Faces: dimension.AttachedFaces))
                    .Concat(view.Annotations.Select(annotation =>
                        (annotation.Id, What: $"annotation type {ProbeText.Int(annotation.TypeRaw)}", Faces: annotation.AttachedFaces)));
                foreach ((string id, string what, List<AttachedFace>? faces) in attached)
                {
                    List<AttachedFace> list = faces ?? new List<AttachedFace>();
                    int attachmentGaps = gaps.Count(gap =>
                        string.Equals(gap.EntityKind, AttachmentGap, StringComparison.Ordinal)
                        && string.Equals(gap.EntityId, id, StringComparison.Ordinal));
                    if (list.Count == 0 && attachmentGaps == 0)
                    {
                        continue;
                    }

                    owners++;
                    lines.Add($"  {id} ({what}, sheet {sheet.Index + 1}, {view.Id}): attached faces {list.Count} "
                        + $"(via face {list.Count(face => face.Via == AttachedVia.Face)}, "
                        + $"via edge {list.Count(face => face.Via == AttachedVia.Edge)}), attachment gaps {attachmentGaps}");
                    for (int i = 0; i < list.Count; i++)
                    {
                        lines.Add($"    face {i + 1} of {list[i].Scope}: {FaceMatch(models, list[i])}");
                    }
                }
            }

            if (owners == 0)
            {
                lines.Add("  no dimension or annotation carries an attachment");
            }

            return lines;
        }

        private static string FaceMatch(ModelReadings models, AttachedFace face)
        {
            ModelReading? reading = models.Readings.FirstOrDefault(
                row => string.Equals(row.DocumentId, face.Scope, StringComparison.Ordinal));
            if (reading?.Package == null)
            {
                return "not compared (the part was not read)";
            }

            FaceGeometry? match = reading.Package.Faces.FirstOrDefault(candidate =>
                string.Equals(candidate.PersistRef, face.PersistRef, StringComparison.Ordinal)
                && string.Equals(candidate.PersistRefScope, face.Scope, StringComparison.Ordinal));
            if (match == null)
            {
                return "no face the part's face phase described has this reference";
            }

            return $"the part's face phase {match.Id} ({PackageSerializer.EnumToJsonName(match.Kind)}"
                + (match.Kind == FaceKind.Cylinder && match.Cylinder != null
                    ? ", radius " + ProbeText.Millimetres(match.Cylinder.RadiusM)
                    : string.Empty)
                + ")";
        }

        // ---- D7 --------------------------------------------------------------------------------

        private IReadOnlyList<string> D7()
        {
            var lines = new List<string>();
            if (!TryRecord(lines, out DrawingRecord record))
            {
                return lines;
            }

            List<(DrawingSheetRecord Sheet, DrawingView View, DisplayDimensionRecord Dimension)> callouts = ViewsOf(record)
                .SelectMany(pair => pair.View.DisplayDimensions
                    .Where(dimension => dimension.IsHoleCallout == true)
                    .Select(dimension => (pair.Sheet, pair.View, dimension)))
                .ToList();
            lines.Add($"  hole callouts in the extraction: {callouts.Count}");
            foreach ((DrawingSheetRecord sheet, DrawingView view, DisplayDimensionRecord dimension) in callouts)
            {
                List<string>? variables = dimension.HoleCalloutVariablesRaw;
                string variableText = variables == null
                    ? $"variables {ProbeText.Unread}"
                    : $"variables {variables.Count} ({string.Join(", ", variables.Select(VariableName))})";
                lines.Add($"  {dimension.Id} {Where(sheet, view)}: IsHoleCallout {ProbeText.Bool(dimension.IsHoleCallout)}, "
                    + $"{variableText}, GetText lengths: 1 {Length(dimension.TextPrefix)}, 2 {Length(dimension.TextSuffix)}, "
                    + $"3 {Length(dimension.TextAbove)}, 4 {Length(dimension.TextBelow)}");
            }

            ProbeAnswer<IReadOnlyList<HoleCalloutText>> whole =
                ProbeAnswer<IReadOnlyList<HoleCalloutText>>.Of(() => _context.Reads.HoleCalloutWholeTexts(_context.Document));
            if (!whole.Answered)
            {
                lines.Add($"  GetText(0) walk failed: {whole.Failure}");
            }
            else if (whole.Value.Count == 0)
            {
                lines.Add("  GetText(0): no dimension answered IsHoleCallout in the direct walk");
            }
            else
            {
                lines.Add("  GetText(0), the whole text, by position (sheet, view, dimension):");
                foreach (HoleCalloutText text in whole.Value)
                {
                    lines.Add($"    {text.Sheet}, {text.View}, {text.Dimension}: "
                        + (text.Failure != null
                            ? $"{ProbeText.Unread} ({text.Failure})"
                            : text.Length == null ? "answered nothing" : $"length {text.Length}"));
                }
            }

            return lines;
        }

        /// <summary>A hole callout variable's name - the part before its value - which is SOLIDWORKS' own token.</summary>
        private static string VariableName(string variable)
        {
            int equals = (variable ?? string.Empty).IndexOf('=');
            return equals < 0 ? variable ?? string.Empty : variable!.Substring(0, equals);
        }

        private static string Length(string? text) =>
            text == null ? ProbeText.Unread : text.Length.ToString(CultureInfo.InvariantCulture);

        // ---- D8 --------------------------------------------------------------------------------

        private IReadOnlyList<string> D8()
        {
            var lines = new List<string>();
            if (!TryRecord(lines, out DrawingRecord record))
            {
                return lines;
            }

            ModelReadings models = Models(record);
            lines.AddRange(models.Lines);
            foreach ((DrawingSheetRecord sheet, DrawingView view) in ViewsOf(record))
            {
                foreach (DisplayDimensionRecord dimension in view.DisplayDimensions)
                {
                    lines.Add($"  {dimension.Id} {Where(sheet, view)}: FullName "
                        + (string.IsNullOrWhiteSpace(dimension.Name)
                            ? ProbeText.Unread
                            : Shape(dimension.Name!, FileNameOf(view.ReferencedModelPath), "the view's document")));
                    lines.Add(PartLine(models, view, dimension, match =>
                        $"    the part: {match.Id} FullName "
                        + Shape(match.Name, FileNameOf(models.PathOf(match.DocumentId)), "the part")
                        + $"; FullName equal {ProbeText.Bool(string.Equals(match.Name, dimension.Name, StringComparison.OrdinalIgnoreCase))}"));
                }
            }

            return lines;
        }

        /// <summary>
        /// A full name's shape, never the name: how many <c>@</c> segments, whether the first is a
        /// default name (printed) or renamed (its length), and whether the last is a document name
        /// (its extension) naming <paramref name="whose"/>.
        /// </summary>
        private static string Shape(string fullName, string? fileName, string whose)
        {
            string[] segments = fullName.Split('@');
            string head = DefaultDimensionName.IsMatch(segments[0])
                ? "default " + segments[0]
                : $"renamed ({segments[0].Length} characters)";
            string last = segments[segments.Length - 1];
            string tail = segments.Length > 1 && ProbeText.KindByExtension(last) != "other"
                ? $"document suffix {ProbeText.Extension(last).ToUpperInvariant()}"
                    + (fileName == null ? string.Empty : $" naming {whose} {ProbeText.Bool(string.Equals(last, fileName, StringComparison.OrdinalIgnoreCase))}")
                : "no document suffix";
            return $"{segments.Length} segments, {head}, {tail}";
        }

        private static string? FileNameOf(string? path) =>
            string.IsNullOrWhiteSpace(path) ? null : ProbeText.FileName(path!);

        // ---- D9 --------------------------------------------------------------------------------

        private const int DatumTag = 2;

        private const int Gtol = 5;

        private const int SurfaceFinish = 7;

        private IReadOnlyList<string> D9()
        {
            var lines = new List<string>();
            if (!TryRecord(lines, out DrawingRecord record))
            {
                return lines;
            }

            List<(DrawingSheetRecord Sheet, DrawingView View, DrawingAnnotation Annotation)> annotations = ViewsOf(record)
                .SelectMany(pair => pair.View.Annotations.Select(annotation => (pair.Sheet, pair.View, annotation)))
                .ToList();
            lines.Add($"  geometric tolerances {annotations.Count(row => row.Annotation.TypeRaw == Gtol)}, "
                + $"datums {annotations.Count(row => row.Annotation.TypeRaw == DatumTag)}, "
                + $"surface finishes {annotations.Count(row => row.Annotation.TypeRaw == SurfaceFinish)}");

            foreach ((DrawingSheetRecord sheet, DrawingView view, DrawingAnnotation annotation) in annotations)
            {
                string where = $"sheet {sheet.Index + 1}, {view.Id}";
                switch (annotation.TypeRaw)
                {
                    case Gtol:
                        string frames = annotation.GtolFrames == null
                            ? $"frames {ProbeText.Unread}"
                            : $"frames {annotation.GtolFrames.Count} (" + string.Join("; ", annotation.GtolFrames.Select(frame =>
                                $"frame {frame.Number}: symbols {frame.SymbolsRaw.Count}, values {frame.ValuesRaw.Count}")) + ")";
                        lines.Add($"  {annotation.Id} (GTol, {where}): {frames}, "
                            + $"datum identifier length {Length(annotation.DatumIdentifierRaw)}");
                        break;
                    case DatumTag:
                        lines.Add($"  {annotation.Id} (datum, {where}): label length {Length(annotation.DatumLabel)}");
                        break;
                    case SurfaceFinish:
                        List<string>? texts = annotation.SurfaceFinishTextsRaw;
                        lines.Add($"  {annotation.Id} (surface finish, {where}): symbol {ProbeText.Int(annotation.SurfaceFinishSymbolRaw)}, "
                            + (texts == null
                                ? $"text slots {ProbeText.Unread}"
                                : $"text slots {texts.Count} (with text {texts.Count(text => !string.IsNullOrEmpty(text))})"));
                        break;
                }
            }

            return lines;
        }

        // ---- D10 -------------------------------------------------------------------------------

        private const int BillOfMaterials = 2;

        private IReadOnlyList<string> D10()
        {
            var lines = new List<string>();
            if (!TryRecord(lines, out DrawingRecord record))
            {
                return lines;
            }

            var tables = record.Sheets.SelectMany(sheet => (sheet.Tables ?? new List<DrawingTable>()).Select(table => (sheet, table))).ToList();
            var revisions = record.Sheets.SelectMany(sheet => sheet.RevisionTables.Select(table => (sheet, table))).ToList();
            lines.Add($"  tables {tables.Count}, revision tables {revisions.Count}");

            HashSet<string> packageDocuments = new HashSet<string>(
                Standards().Package!.Documents.Select(document => document.DocumentId), StringComparer.Ordinal);
            foreach ((DrawingSheetRecord sheet, DrawingTable table) in tables)
            {
                lines.Add($"  {table.Id} (sheet {sheet.Index + 1}): type {ProbeText.Int(table.TableTypeRaw)}, "
                    + Cells(table.RowCount, table.ColumnCount, table.Rows));
                if (table.BomRows != null)
                {
                    foreach (BomRow row in table.BomRows)
                    {
                        lines.Add($"    bill of materials row {row.Index}: " + BomRowText(row, packageDocuments));
                    }
                }
                else if (table.TableTypeRaw == BillOfMaterials)
                {
                    lines.Add($"    bill of materials rows {ProbeText.Unread}");
                }
            }

            foreach ((DrawingSheetRecord sheet, RevisionTable table) in revisions)
            {
                lines.Add($"  {table.Id} (sheet {sheet.Index + 1}): revision table, "
                    + Cells(table.RowCount, table.ColumnCount, table.Rows));
            }

            return lines;
        }

        private static string Cells(int? rowCount, int? columnCount, List<RevisionTableRow> rows)
        {
            int readable = rows.Sum(row => row.Cells.Count(cell => cell != null));
            int of = rowCount != null && columnCount != null ? rowCount.Value * columnCount.Value : rows.Sum(row => row.Cells.Count);
            return $"rows {ProbeText.Int(rowCount)}, columns {ProbeText.Int(columnCount)}, readable cells {readable} of {of}";
        }

        private string BomRowText(BomRow row, HashSet<string> packageDocuments)
        {
            if (row.DocumentIds == null && row.UnresolvedPaths == null)
            {
                return $"model paths {ProbeText.Unread}";
            }

            List<string> resolved = row.DocumentIds ?? new List<string>();
            List<string> unresolved = row.UnresolvedPaths ?? new List<string>();
            ProbeAnswer<int> open = ProbeAnswer<int>.Of(() =>
                resolved.Count(packageDocuments.Contains) + unresolved.Count(_context.Reads.IsOpen));
            return $"model paths {resolved.Count + unresolved.Count}, open documents {open.Print(value => value.ToString(CultureInfo.InvariantCulture))}";
        }

        // ---- D11 -------------------------------------------------------------------------------

        private IReadOnlyList<string> D11()
        {
            var lines = new List<string>();
            if (!TryRecord(lines, out DrawingRecord record))
            {
                return lines;
            }

            ProbeAnswer<IReadOnlyList<int?>> counts =
                ProbeAnswer<IReadOnlyList<int?>>.Of(() => _context.Reads.SheetPropertyCounts(_context.Document));
            foreach (DrawingSheetRecord sheet in record.Sheets)
            {
                string items = !counts.Answered
                    ? $"{ProbeText.Unread} ({counts.Failure})"
                    : ProbeText.Int(sheet.Index < counts.Value.Count ? counts.Value[sheet.Index] : null);
                string scale = sheet.ScaleNumerator == null || sheet.ScaleDenominator == null
                    ? ProbeText.Unread
                    : $"{ProbeText.Number(sheet.ScaleNumerator)}:{ProbeText.Number(sheet.ScaleDenominator)}";
                lines.Add($"  sheet {sheet.Index + 1}: GetProperties2 items {items}, scale {scale}, "
                    + $"first angle {ProbeText.Bool(sheet.FirstAngle)}, GetTemplateName present {ProbeText.Bool(sheet.SheetFormatPath != null)}");
            }

            ProbeAnswer<int> standard = ProbeAnswer<int>.Of(
                () => _context.Reads.UserPreferenceInteger(_context.Document, DimensionStandardPreference));
            lines.Add($"  preferences: 13 (swDetailingDimensionStandard) {standard.Print(value => ProbeText.Int(value))}, "
                + $"47 (swUnitsLinear) {ProbeText.Int(record.LengthUnitRaw)}, "
                + $"65 (swDetailingDimensionStandardName) answered {ProbeText.Bool(record.DraftingStandardName != null)}");
            return lines;
        }

        // ---- D12 -------------------------------------------------------------------------------

        private IReadOnlyList<string> D12()
        {
            var lines = new List<string>();
            if (!TryRecord(lines, out DrawingRecord record))
            {
                return lines;
            }

            lines.Add($"  detailing mode {ProbeText.Bool(record.IsDetailingMode)}");
            foreach ((DrawingSheetRecord sheet, DrawingView view) in ViewsOf(record))
            {
                lines.Add($"  {view.Id} (sheet {sheet.Index + 1}): "
                    + $"ReferencedConfiguration present {ProbeText.Bool(view.ReferencedConfiguration != null)}, "
                    + $"IsModelOutOfDate {ProbeText.Bool(view.IsModelOutOfDate)}, IsModelLoaded {ProbeText.Bool(view.IsModelLoaded)}");
            }

            return lines;
        }

        // ---- D13 -------------------------------------------------------------------------------

        private IReadOnlyList<string> D13()
        {
            if (_context.DocumentPath == null)
            {
                return new[] { "  the document has never been saved, so no same-name drawing is asked about" };
            }

            string candidate = OpenDrawingDiscovery.CandidatePath(_context.DocumentPath);
            ProbeAnswer<ProbeFileEntry> before = ProbeAnswer<ProbeFileEntry>.Of(() => _context.Files.Entry(candidate));
            long start = _context.ClockMilliseconds();
            ProbeAnswer<bool> exists = ProbeAnswer<bool>.Of(() => _context.Files.Exists(candidate));
            long elapsed = _context.ClockMilliseconds() - start;
            ProbeAnswer<ProbeFileEntry> after = ProbeAnswer<ProbeFileEntry>.Of(() => _context.Files.Entry(candidate));

            return new[]
            {
                exists.Answered
                    ? $"  File.Exists {ProbeText.Bool(exists.Value)} in {elapsed} ms"
                    : $"  File.Exists failed after {elapsed} ms: {exists.Failure}",
                $"  directory entry before: {before.Print(EntryText)}; after: {after.Print(EntryText)}",
                "  the local copy changed across the check: "
                    + (before.Answered && after.Answered ? ProbeText.Bool(!before.Value.Equals(after.Value)) : ProbeText.Unread),
            };
        }

        private static string EntryText(ProbeFileEntry entry) =>
            !entry.Present
                ? "absent"
                : string.Format(
                    CultureInfo.InvariantCulture, "present, length {0}, attributes 0x{1:X8}", entry.Length, entry.Attributes);

        // ---- shared --------------------------------------------------------------------------

        /// <summary>The open drawing's Standards extraction, taken once, its failure remembered rather than retried.</summary>
        private PackageReading Standards()
        {
            if (_standards == null)
            {
                long start = _context.ClockMilliseconds();
                ProbeAnswer<EvidencePackage> package = ProbeAnswer<EvidencePackage>.Of(() => _context.Build(StandardsOptions()));
                long elapsed = _context.ClockMilliseconds() - start;
                _standards = new PackageReading(package.Answered ? package.Value : null, package.Failure, elapsed);
            }

            return _standards;
        }

        /// <summary>
        /// The drawing's record from the Standards extraction - the root's when several - or false
        /// with the line that says why there is none.
        /// </summary>
        private bool TryRecord(List<string> lines, out DrawingRecord record)
        {
            record = null!;
            PackageReading reading = Standards();
            if (reading.Package == null)
            {
                lines.Add($"  not read: the Standards extraction stopped ({reading.Failure})");
                return false;
            }

            List<DrawingRecord> records = reading.Package.DrawingRecords ?? new List<DrawingRecord>();
            DrawingRecord? found = records.FirstOrDefault(row => string.Equals(
                    row.DocumentId, reading.Package.Design.RootAssemblyDocumentId, StringComparison.Ordinal))
                ?? records.FirstOrDefault();
            if (found == null)
            {
                lines.Add("  the extraction produced no drawing record");
                return false;
            }

            record = found;
            return true;
        }

        private static IEnumerable<(DrawingSheetRecord Sheet, DrawingView View)> ViewsOf(DrawingRecord record) =>
            record.Sheets.SelectMany(sheet => sheet.Views.Select(view => (sheet, view)));

        private static string Where(DrawingSheetRecord sheet, DrawingView view) => $"(sheet {sheet.Index + 1}, {view.Id})";

        /// <summary>
        /// The part documents the drawing shows or its annotations attach to, in the order first met,
        /// each extracted once (at most <see cref="MaxModelReadings"/>) - only when SOLIDWORKS has it
        /// open; nothing is opened to take it.
        /// </summary>
        private ModelReadings Models(DrawingRecord record)
        {
            if (_models != null)
            {
                return _models;
            }

            EvidencePackage package = Standards().Package!;
            Dictionary<string, Document> documents = package.Documents
                .GroupBy(document => document.DocumentId, StringComparer.Ordinal)
                .ToDictionary(group => group.Key, group => group.First(), StringComparer.Ordinal);

            var wanted = new List<string>();
            void Want(string? id)
            {
                if (!string.IsNullOrWhiteSpace(id) && !wanted.Contains(id!, StringComparer.Ordinal)
                    && (!documents.TryGetValue(id!, out Document? document) || document.Kind == DocumentKind.Part))
                {
                    wanted.Add(id!);
                }
            }

            foreach ((DrawingSheetRecord _, DrawingView view) in ViewsOf(record))
            {
                Want(view.ReferencedDocumentId);
            }

            foreach ((DrawingSheetRecord _, DrawingView view) in ViewsOf(record))
            {
                foreach (AttachedFace face in view.DisplayDimensions.SelectMany(d => d.AttachedFaces ?? new List<AttachedFace>())
                             .Concat(view.Annotations.SelectMany(a => a.AttachedFaces ?? new List<AttachedFace>())))
                {
                    Want(face.Scope);
                }
            }

            var readings = new List<ModelReading>();
            var lines = new List<string>();
            foreach (string id in wanted.Take(MaxModelReadings))
            {
                if (!documents.TryGetValue(id, out Document? document) || string.IsNullOrWhiteSpace(document.Path))
                {
                    readings.Add(new ModelReading(id, null, null));
                    lines.Add($"  the part's own extraction: {id} is not a document of the drawing's extraction, so it was not read");
                    continue;
                }

                ProbeAnswer<EvidencePackage?> built = ProbeAnswer<EvidencePackage?>.Of(
                    () => _context.BuildOpenModel(document.Path, ModelOptions()));
                readings.Add(new ModelReading(id, document.Path, built.Answered ? built.Value : null));
                if (!built.Answered)
                {
                    lines.Add($"  the part's own extraction: {id} stopped: {built.Failure}");
                }
                else if (built.Value == null)
                {
                    lines.Add($"  the part's own extraction: {id} is not open, so it was not read (nothing is opened)");
                }
                else
                {
                    int dimensions = (built.Value.ModelDimensions ?? new List<ModelDimension>())
                        .Count(model => string.Equals(model.DocumentId, id, StringComparison.Ordinal));
                    int faces = built.Value.Faces.Count(face => string.Equals(face.PersistRefScope, id, StringComparison.Ordinal));
                    lines.Add($"  the part's own extraction: {id} read, {ProbeText.Count(dimensions, "model dimension")}, "
                        + ProbeText.Count(faces, "face"));
                }
            }

            if (wanted.Count == 0)
            {
                lines.Add("  the part's own extraction: the drawing shows no part and attaches to none, so none was read");
            }
            else if (wanted.Count > MaxModelReadings)
            {
                lines.Add($"  {wanted.Count - MaxModelReadings} more part documents were not read: the probe reads at most {MaxModelReadings}");
            }

            _models = new ModelReadings(readings, lines);
            return _models;
        }
    }

    /// <summary>An extraction as the run took it: the package, or why there is none, and what it cost.</summary>
    private sealed class PackageReading
    {
        public PackageReading(EvidencePackage? package, string? failure, long elapsedMs)
        {
            Package = package;
            Failure = failure;
            ElapsedMs = elapsedMs;
        }

        public EvidencePackage? Package { get; }

        public string? Failure { get; }

        public long ElapsedMs { get; }
    }

    /// <summary>One part's own extraction, or null when it was not open, not found or failed.</summary>
    private sealed class ModelReading
    {
        public ModelReading(string documentId, string? path, EvidencePackage? package)
        {
            DocumentId = documentId;
            Path = path;
            Package = package;
        }

        public string DocumentId { get; }

        public string? Path { get; }

        public EvidencePackage? Package { get; }
    }

    /// <summary>Every part reading of the run, and the lines that say how each went.</summary>
    private sealed class ModelReadings
    {
        public ModelReadings(IReadOnlyList<ModelReading> readings, IReadOnlyList<string> lines)
        {
            Readings = readings;
            Lines = lines;
        }

        public IReadOnlyList<ModelReading> Readings { get; }

        public IReadOnlyList<string> Lines { get; }

        public string? PathOf(string documentId) =>
            Readings.FirstOrDefault(reading => string.Equals(reading.DocumentId, documentId, StringComparison.Ordinal))?.Path;
    }
}
