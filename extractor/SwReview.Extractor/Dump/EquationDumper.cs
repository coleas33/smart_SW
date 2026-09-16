using System;
using System.Collections.Generic;
using System.IO;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Dump;

/// <summary>
/// The live reads <see cref="EquationDumper"/> needs, with no interop type in the signature
/// (<see cref="SwEquationReader"/> is the SOLIDWORKS one). The seam exists so the dumper's
/// policy - one manager per document, what becomes a gap, what is left null - is unit
/// tested on a machine with no seat, exactly as <see cref="IFeatureReader"/> is.
///
/// Every member here maps to ONE interop call and is gated by the dumper, which names it,
/// so the read-only guard and the SC-004 audit see the production member names even under a
/// fake.
/// </summary>
public interface IEquationReader
{
    /// <summary><c>IComponent2.GetModelDoc2</c>; null when the document is not loaded.</summary>
    object? Document(ScopedComponent component);

    /// <summary>
    /// <c>IModelDoc2.GetEquationMgr</c>; null when SOLIDWORKS handed over no manager, which
    /// the dumper records as a gap rather than as an empty equation list.
    /// </summary>
    object? Manager(object document);

    /// <summary><c>IEquationMgr.GetCount</c>.</summary>
    int Count(object manager);

    /// <summary><c>IEquationMgr.Equation(i)</c> verbatim; may be null.</summary>
    string? Text(object manager, int index);

    /// <summary>
    /// <c>IEquationMgr.GlobalVariable(i)</c>. The ONLY source of "is this a global": the
    /// text of a global and of a driven dimension are not reliably told apart by parsing
    /// (research R5), and both parametric rules turn on this flag.
    /// </summary>
    bool GlobalVariable(object manager, int index);

    /// <summary><c>IEquationMgr.Value(i)</c>.</summary>
    double Value(object manager, int index);
}

/// <summary>
/// T038. The equation manager of every part document the assembly resolves, once per
/// document, for <c>rms.params.global_variables_present</c> and
/// <c>rms.params.dimensions_driven_by_equations</c>.
///
/// The same three rules shape it as <see cref="FeatureDumper"/>:
///
///   * <b>Once per document.</b> A part instanced forty times has one equation list.
///   * <b>Nothing is resolved.</b> A lightweight, suppressed or unloaded component is an
///     <c>equations</c> gap; resolving it would change the session the engineer is in.
///   * <b>Nothing is defaulted.</b> A failed read is null plus an <c>equations</c> gap, so
///     the rules report unresolved rather than "this part has no global variables"
///     (constitution Principle I). The one thing that is NOT a gap is a manager that was
///     read and holds nothing: a part with no equations is exactly what the global-variables
///     rule exists to find, and a gap there would turn every such finding into unresolved
///     coverage. A manager SOLIDWORKS never handed over is the other case, and IS a gap.
///
/// Every gap that stands for a whole document is recorded under the DOCUMENT id, because
/// that is how the rules look one up (<c>checks/rms/part.py</c>, <c>document_gap</c>); a gap
/// naming a component says "this instance was unreadable" and is invisible to them.
///
/// The root assembly's own equations are deliberately not read:
/// <c>rms.assembly.positions_driven_by_globals</c> is unresolved coverage by construction
/// ("assembly equations not extracted", contracts/rules.md), so no row here claims to
/// describe an assembly.
/// </summary>
public sealed class EquationDumper : IEquationSource
{
    /// <summary>The gap entity kind every unread equation is recorded under (data-model section 1).</summary>
    private const string EntityKind = "equations";

    private readonly SwGate _gate;
    private readonly IEquationReader _reader;

    public EquationDumper(SwGate gate, IEquationReader reader)
    {
        _gate = gate ?? throw new ArgumentNullException(nameof(gate));
        _reader = reader ?? throw new ArgumentNullException(nameof(reader));
    }

    public IReadOnlyList<Equation> Dump(DumpScope scope)
    {
        if (scope == null)
        {
            throw new ArgumentNullException(nameof(scope));
        }

        var rows = new List<Equation>();
        var read = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var unopened = new Dictionary<string, UnopenedDocument>(StringComparer.OrdinalIgnoreCase);

        foreach (ScopedComponent component in scope.Components)
        {
            ComponentNode node = component.Node;

            if (node.DocumentKind != DocumentKind.Part || read.Contains(node.DocumentPath))
            {
                continue;
            }

            if (node.Suppression != SuppressionState.Resolved)
            {
                // Deliberately not marked as read: a later instance of the same part may be
                // resolved, and that one carries the equations.
                scope.Gaps.Add(
                    GapKind.NotExtracted,
                    EntityKind,
                    component.Id,
                    $"'{node.Key}' is {PackageSerializer.EnumToJsonName(node.Suppression)}, so its "
                    + "equations were not read; it was not resolved, because resolving it would "
                    + "change the open session.",
                    null);
                continue;
            }

            object? document = null;
            if (!scope.Gaps.TryStep(
                EntityKind,
                component.Id,
                $"open the model document for '{node.Key}'",
                () => { document = _gate.Call("GetModelDoc2", () => _reader.Document(component)); }))
            {
                Note(unopened, component, $"opening the model document for '{node.Key}' failed");
                continue;
            }

            if (document == null)
            {
                scope.Gaps.Add(
                    GapKind.NotExtracted,
                    EntityKind,
                    component.Id,
                    $"'{node.Key}' has no loaded model document, so its equations were not read.",
                    null);
                Note(unopened, component, $"'{node.Key}' has no loaded model document");
                continue;
            }

            read.Add(node.DocumentPath);
            rows.AddRange(DumpDocument(scope, component, document!));
        }

        RecordUnopened(scope, read, unopened);
        return rows;
    }

    /// <summary>A part document an instance failed to open: its id, and why the first try failed.</summary>
    private readonly struct UnopenedDocument
    {
        public UnopenedDocument(string documentId, string reason)
        {
            DocumentId = documentId;
            Reason = reason;
        }

        public string DocumentId { get; }

        public string Reason { get; }
    }

    /// <summary>
    /// Remembers that this instance could not be opened. The first failure's reason is the
    /// one kept: a second instance failing the same way says nothing new, and the document is
    /// named once either way.
    /// </summary>
    private static void Note(
        IDictionary<string, UnopenedDocument> unopened, ScopedComponent component, string reason)
    {
        if (!unopened.ContainsKey(component.Node.DocumentPath))
        {
            unopened[component.Node.DocumentPath] =
                new UnopenedDocument(component.DocumentId, reason);
        }
    }

    /// <summary>
    /// One <c>equations</c> gap per part document NO instance could open, under the document
    /// id.
    ///
    /// The per-instance gaps in the walk name a component, which is the honest subject of
    /// "this instance was unreadable" - but the rules ask for a document's gap by document id
    /// (<c>checks/rms/part.py</c>, <c>document_gap</c>), so a component-scoped gap alone
    /// leaves both parametric rules grading an empty equation list and reporting "this part
    /// has no global variables" about a document nobody opened (constitution Principle I).
    ///
    /// Deferred to the end of the walk for the same reason a failed instance does not mark
    /// its document as read: a later instance of the same part may open, and a document whose
    /// rows WERE read is an answer, not a gap.
    /// </summary>
    private static void RecordUnopened(
        DumpScope scope,
        HashSet<string> read,
        Dictionary<string, UnopenedDocument> unopened)
    {
        foreach (KeyValuePair<string, UnopenedDocument> entry in unopened)
        {
            if (read.Contains(entry.Key))
            {
                continue;
            }

            scope.Gaps.Add(
                GapKind.NotExtracted,
                EntityKind,
                entry.Value.DocumentId,
                $"The equations of {Path.GetFileName(entry.Key)} were not read: "
                + $"{entry.Value.Reason}.",
                null);
        }
    }

    /// <summary>One document's rows, or none when its manager could not be read.</summary>
    private IReadOnlyList<Equation> DumpDocument(
        DumpScope scope, ScopedComponent component, object document)
    {
        string documentId = component.DocumentId;
        string fileName = Path.GetFileName(component.Node.DocumentPath);

        object? manager = null;
        if (!scope.Gaps.TryStep(
            EntityKind,
            documentId,
            $"open the equation manager of {fileName}",
            () => { manager = _gate.Call("GetEquationMgr", () => _reader.Manager(document)); }))
        {
            // A read that threw is already a gap.
            return Array.Empty<Equation>();
        }

        if (manager == null)
        {
            // SOLIDWORKS handed over no manager at all, which is not the same answer as a
            // manager that holds nothing: nobody read one. Without this gap both parametric
            // rules would report "the equation manager holds no equations" about data that
            // was never available (constitution Principle I). The empty list that IS an
            // answer is GetCount == 0, below.
            scope.Gaps.Add(
                GapKind.NotExtracted,
                EntityKind,
                documentId,
                $"{fileName} returned no equation manager, so its equations were not read.",
                null);
            return Array.Empty<Equation>();
        }

        object found = manager!;
        int count = 0;
        if (!scope.Gaps.TryStep(
            EntityKind,
            documentId,
            $"read the equation count of {fileName}",
            () => { count = _gate.Call("GetCount", () => _reader.Count(found)); }))
        {
            return Array.Empty<Equation>();
        }

        var rows = new List<Equation>(count);
        for (int i = 0; i < count; i++)
        {
            Equation? row = ReadEquation(scope, documentId, fileName, found, i);
            if (row != null)
            {
                rows.Add(row!);
            }
        }

        return rows;
    }

    /// <summary>
    /// One row, or null plus a gap when its text could not be read. Every other read is
    /// allowed to fail on its own: a null <c>is_global</c> makes both parametric rules
    /// unresolved for the document, which is the honest answer, while the text is what the
    /// finding shows the engineer and a row without it would be evidence of nothing.
    /// </summary>
    private Equation? ReadEquation(
        DumpScope scope, string documentId, string fileName, object manager, int index)
    {
        string? text = null;
        if (!scope.Gaps.TryStep(
            EntityKind,
            documentId,
            $"read equation {index} of {fileName}",
            () => { text = _gate.Call("EquationMgr.Equation", () => _reader.Text(manager, index)); }))
        {
            return null;
        }

        if (text == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                EntityKind,
                documentId,
                $"Equation {index} of {fileName} has no text, so it was not recorded; the "
                + "document's equation list is shorter than SOLIDWORKS reported.",
                null);
            return null;
        }

        bool? isGlobal = null;
        scope.Gaps.TryStep(
            EntityKind,
            documentId,
            $"read GlobalVariable for equation {index} of {fileName}",
            () =>
            {
                isGlobal = _gate.Call("GlobalVariable", () => _reader.GlobalVariable(manager, index));
            });

        double? value = null;
        scope.Gaps.TryStep(
            EntityKind,
            documentId,
            $"read Value for equation {index} of {fileName}",
            () => { value = _gate.Call("EquationMgr.Value", () => _reader.Value(manager, index)); });

        return new Equation
        {
            DocumentId = documentId,
            Index = index,
            Text = text!,
            Lhs = Equation.LhsOf(text!),
            IsGlobal = isGlobal,
            Value = value,
        };
    }

}
