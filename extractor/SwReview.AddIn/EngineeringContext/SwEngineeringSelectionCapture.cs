using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.AddIn.Review;
using SwReview.Extractor.Geometry;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;

namespace SwReview.AddIn.EngineeringContext;

/// <summary>Read-only application-thread selection adapter; never opens or selects anything.</summary>
public sealed class SwEngineeringSelectionCapture : IEngineeringSelectionCapture
{
    private const int MaximumPackageBytes = 64 * 1024 * 1024;
    private const int MaximumIdentityCandidates = 256;
    private static readonly Regex NativeReferenceLabel = new Regex(
        @"\b(?:persist_ref|persistent_reference|native_reference)\s*[:=]", RegexOptions.IgnoreCase);
    private static readonly Regex SourcePathLabel = new Regex(@"[A-Za-z]:[\\/]|\\\\|(?:^|\s)/");
    private readonly ISldWorks _application;
    private readonly IApplicationThread _thread;

    public SwEngineeringSelectionCapture(ISldWorks application, IApplicationThread thread)
    {
        _application = application ?? throw new ArgumentNullException(nameof(application));
        _thread = thread ?? throw new ArgumentNullException(nameof(thread));
    }

    public EngineeringSelectionObservation Capture(string runDirectory, string expectedPackageSha256)
    {
        var result = new EngineeringSelectionObservation();
        string packagePath;
        EvidencePackage package;
        try
        {
            if (string.IsNullOrWhiteSpace(runDirectory) || !Path.IsPathRooted(runDirectory)
                || expectedPackageSha256 == null || expectedPackageSha256.Length != 64
                || expectedPackageSha256.Any(value => !"0123456789abcdef".Contains(value)))
            {
                return Unresolved(result, "package_input_invalid");
            }

            packagePath = Path.Combine(runDirectory, "package.json");
            byte[] bytes = ReadPackage(packagePath);
            string digest = Digest(bytes);
            if (!string.Equals(digest, expectedPackageSha256, StringComparison.Ordinal))
            {
                return Unresolved(result, "package_digest_mismatch");
            }

            package = PackageSerializer.Deserialize(Encoding.UTF8.GetString(bytes));
            if (!package.SchemaVersion.StartsWith("1.", StringComparison.Ordinal)
                || package.PackageId == Guid.Empty || package.Documents == null
                || package.Components == null || package.Faces == null || package.Design == null
                || package.Documents.Select(row => row.DocumentId).Distinct().Count() != package.Documents.Count
                || package.Components.Select(row => row.Id).Distinct().Count() != package.Components.Count
                || package.Faces.Select(row => row.Id).Distinct().Count() != package.Faces.Count)
            {
                return Unresolved(result, "package_invalid");
            }

            result.PackageId = package.PackageId;
            result.PackageSha256 = digest;
        }
        catch (Exception)
        {
            return Unresolved(result, "package_unavailable");
        }

        try
        {
            _thread.Invoke(() => Observe(package, result));
            // The saved package may change independently of the application-thread observation.
            if (!string.Equals(Digest(ReadPackage(packagePath)), expectedPackageSha256, StringComparison.Ordinal))
            {
                return Unresolved(result, "package_changed");
            }

            return result;
        }
        catch (SelectionUnresolved refusal)
        {
            return Unresolved(result, refusal.Reason);
        }
        catch (Exception)
        {
            // COM exception messages can contain engineer paths, so only the coverage code travels.
            return Unresolved(result, "native_read_failed");
        }
    }

    private bool Observe(EvidencePackage package, EngineeringSelectionObservation result)
    {
        var gate = new SwGate();
        var refs = new PersistRefService(gate);
        var root = gate.Call("ActiveDoc", () => _application.ActiveDoc) as IModelDoc2;
        Require(root != null, "active_document_unavailable");
        ModelState before = ReadState(root!, gate);
        result.RootDocumentId = before.DocumentId;
        result.RootConfiguration = before.Configuration;
        result.RootDirty = before.Dirty;
        result.RootDirtyReliable = before.DirtyReliable;
        Require(before.Type == 1 || before.Type == 2, "root_unsupported");
        Require(before.DocumentId == package.Design.RootAssemblyDocumentId
            && before.Configuration == package.Design.ActiveConfiguration, "root_package_mismatch");
        Document? savedRoot = package.Documents.SingleOrDefault(row => row.DocumentId == before.DocumentId);
        Require(savedRoot != null && DocumentIds.For(savedRoot.Path) == before.DocumentId
            && savedRoot.Configurations.Contains(before.Configuration), "root_package_mismatch");
        RequireClean(before, "root");

        var selection = gate.Call("SelectionManager", () => root!.SelectionManager) as ISelectionMgr;
        Require(selection != null, "selection_unavailable");
        int count = gate.Call("GetSelectedObjectCount2", () => selection!.GetSelectedObjectCount2(-1));
        Require(count > 0, "selection_empty");
        Require(count == 1, "selection_multiple");
        object? selected = gate.Call("GetSelectedObject6", () => selection!.GetSelectedObject6(1, -1));
        var face = selected as IFace2;
        var component = selected as IComponent2;
        Require(face != null || component != null, "selection_unsupported");
        if (face != null && before.Type == 2)
        {
            var entity = selected as IEntity;
            Require(entity != null, "occurrence_unavailable");
            // Read occurrence identity before mapping, which removes assembly context.
            component = gate.Call("Entity.GetComponent", () => entity!.GetComponent()) as IComponent2;
            Require(component != null, "occurrence_unavailable");
        }

        Require(component != null || before.Type == 1, "occurrence_unavailable");
        OccurrenceState? occurrence = component == null ? null : ReadOccurrence(component, gate);
        IModelDoc2 owner = occurrence?.Owner ?? root!;
        ModelState ownerBefore = SameObject(owner, root!) ? before : ReadState(owner, gate);
        result.OwnerDirty = ownerBefore.Dirty;
        result.OwnerDirtyReliable = ownerBefore.DirtyReliable;
        RequireClean(ownerBefore, "owner");
        Require(face == null || ownerBefore.Type == 1, "face_owner_unsupported");
        if (occurrence != null)
        {
            Require(DocumentIds.For(occurrence.Path) == ownerBefore.DocumentId, "owner_document_mismatch");
            // A component's owner may have a different active config; a face cannot be mapped
            // from a configuration we did not observe. Never switch configurations to answer.
            Require(face == null || occurrence.Configuration == ownerBefore.Configuration,
                "owner_configuration_mismatch");
        }

        object occurrenceEntity = (object?)component ?? root!;
        string occurrenceReference = refs.Get(root!, occurrenceEntity).Base64;
        List<ComponentInstance> candidates = package.Components.Where(row =>
            row.DocumentId == ownerBefore.DocumentId && row.PersistRefScope == before.DocumentId
            && (occurrence == null
                ? row.ParentId == null && row.ReferencedConfiguration == before.Configuration
                : row.ParentId != null && row.FullPath == occurrence.FullPath
                    && row.ReferencedConfiguration == occurrence.Configuration)).ToList();
        Require(candidates.Count <= MaximumIdentityCandidates, "identity_candidates_truncated");
        List<ComponentInstance> matches = IdentityMatches(candidates, row => row.PersistRef,
            root!, occurrenceReference, gate);
        Require(matches.Count > 0, "occurrence_not_in_package");
        Require(matches.Count == 1, "occurrence_ambiguous");
        ComponentInstance matched = matches[0];
        RequireSavedOccurrence(matched, package, occurrence?.Ancestors);
        if (occurrence != null)
        {
            Require(SameTransform(matched.Transform, occurrence.Transform), "occurrence_transform_mismatch");
        }

        FaceGeometry? savedFace = null;
        if (face != null)
        {
            object partFace = face;
            if (before.Type == 2)
            {
                IModelDocExtension? extension = gate.Call("Extension", () => owner.Extension);
                Require(extension != null, "face_mapping_unavailable");
                object? corresponding = gate.Call(
                    "GetCorrespondingEntity2", () => extension!.GetCorrespondingEntity2(face));
                Require(corresponding is IFace2, "face_mapping_unavailable");
                partFace = corresponding!;
            }

            string faceReference = refs.Get(owner, partFace).Base64;
            List<FaceGeometry> faceCandidates = package.Faces.Where(row =>
                row.ComponentId == matched.Id && row.PersistRefScope == ownerBefore.DocumentId).ToList();
            Require(faceCandidates.Count <= MaximumIdentityCandidates, "identity_candidates_truncated");
            List<FaceGeometry> faceMatches = IdentityMatches(faceCandidates, row => row.PersistRef,
                owner, faceReference, gate);
            Require(faceMatches.Count > 0, "face_not_in_package");
            Require(faceMatches.Count == 1, "face_ambiguous");
            savedFace = faceMatches[0];
        }

        // No stored session or cached component IDs are used. Check the same live handles again.
        var activeAfter = gate.Call("ActiveDoc", () => _application.ActiveDoc) as IModelDoc2;
        Require(activeAfter != null && SameObject(root!, activeAfter), "active_document_changed");
        ModelState rootAfter = ReadState(root!, gate);
        result.RootDirty = rootAfter.Dirty;
        result.RootDirtyReliable = rootAfter.DirtyReliable;
        Require(before.SameAs(rootAfter), "root_state_changed");
        ModelState ownerAfter = ReadState(owner, gate);
        result.OwnerDirty = ownerAfter.Dirty;
        result.OwnerDirtyReliable = ownerAfter.DirtyReliable;
        Require(ownerBefore.SameAs(ownerAfter), "owner_state_changed");
        if (component != null)
        {
            Require(occurrence!.SameAs(ReadOccurrence(component, gate)), "occurrence_state_changed");
            if (face != null)
            {
                Require(SameObject(component, gate.Call("Entity.GetComponent", () => ((IEntity)face).GetComponent())),
                    "occurrence_state_changed");
            }
        }

        var selectionAfter = gate.Call("SelectionManager", () => root!.SelectionManager) as ISelectionMgr;
        Require(selectionAfter != null, "selection_changed");
        Require(gate.Call("GetSelectedObjectCount2", () => selectionAfter!.GetSelectedObjectCount2(-1)) == 1,
            "selection_changed");
        Require(SameObject(selected!, gate.Call("GetSelectedObject6", () => selectionAfter!.GetSelectedObject6(1, -1))),
            "selection_changed");

        result.Status = "matched_saved_target";
        result.Kind = savedFace == null ? "component" : "face";
        result.EntityId = savedFace?.Id ?? matched.Id;
        result.ComponentId = matched.Id;
        result.DocumentId = matched.DocumentId;
        result.Configuration = matched.ReferencedConfiguration;
        Document? savedOwner = package.Documents.SingleOrDefault(row => row.DocumentId == matched.DocumentId);
        string fileName = Path.GetFileName((savedOwner?.FileName ?? string.Empty).Replace('/', '\\'));
        result.DisplayName = SafeLabel(matched.FullPath, SafeLabel(matched.Name, "Saved occurrence"))
            + " — " + SafeLabel(fileName, "Saved document")
            + " [" + SafeLabel(matched.ReferencedConfiguration, "Configuration omitted") + "]";
        return true;
    }

    private static string SafeLabel(string value, string fallback)
    {
        if (string.IsNullOrWhiteSpace(value) || Path.IsPathRooted(value) || SourcePathLabel.IsMatch(value)
            || NativeReferenceLabel.IsMatch(value) || value.Any(char.IsControl)
            || value.Split('/', '\\').Any(segment => segment == ".."))
        {
            return fallback;
        }

        return value.Length <= 1024 ? value : value.Substring(0, 1024) + " [label truncated]";
    }

    private ModelState ReadState(IModelDoc2 document, SwGate gate)
    {
        string path = gate.Call("GetPathName", document.GetPathName);
        Require(!string.IsNullOrWhiteSpace(path), "document_unsaved");
        int type = gate.Call("GetType", () => document.GetType());
        var configuration = gate.Call(
            "ConfigurationManager.ActiveConfiguration", () => document.ConfigurationManager?.ActiveConfiguration)
            as IConfiguration;
        Require(configuration != null, "configuration_unknown");
        string name = gate.Call("Configuration.Name", () => configuration!.Name);
        Require(!string.IsNullOrWhiteSpace(name), "configuration_unknown");
        bool dirty = gate.Call("GetSaveFlag", document.GetSaveFlag);
        bool readOnly = gate.Call("IsOpenedReadOnly", document.IsOpenedReadOnly);
        bool discardsChanges = readOnly && gate.Call("GetUserPreferenceToggle", () =>
            _application.GetUserPreferenceToggle((int)swUserPreferenceToggle_e.swExtRefNoPromptOrSave));
        return new ModelState(DocumentIds.For(path), type, name, dirty, readOnly, !discardsChanges);
    }

    private static OccurrenceState ReadOccurrence(IComponent2 component, SwGate gate)
    {
        int suppression = gate.Call("GetSuppression2", component.GetSuppression2);
        Require(suppression == (int)swComponentSuppressionState_e.swComponentFullyResolved
            || suppression == (int)swComponentSuppressionState_e.swComponentResolved, "occurrence_unavailable");
        var owner = gate.Call("GetModelDoc2", component.GetModelDoc2) as IModelDoc2;
        Require(owner != null, "owner_unavailable");
        string path = gate.Call("Component.GetPathName", component.GetPathName);
        string fullPath = gate.Call("Name2", () => component.Name2);
        string configuration = gate.Call("ReferencedConfiguration", () => component.ReferencedConfiguration);
        Require(!string.IsNullOrWhiteSpace(path) && !string.IsNullOrWhiteSpace(fullPath)
            && !string.IsNullOrWhiteSpace(configuration), "occurrence_metadata_unknown");
        IMathTransform? transform = gate.Call("Transform2", () => component.Transform2);
        Require(transform != null, "occurrence_transform_unavailable");
        double[][]? matrix = SwTransform.FromComValue(gate.Call("ArrayData", () => transform!.ArrayData));
        Require(matrix != null, "occurrence_transform_unavailable");
        return new OccurrenceState(owner!, path, fullPath, configuration, matrix!, ReadAncestors(component, gate));
    }

    private static IReadOnlyList<AncestorState> ReadAncestors(IComponent2 component, SwGate gate)
    {
        var ancestors = new List<AncestorState>();
        var seen = new List<object> { component };
        var current = gate.Call("GetParent", component.GetParent) as IComponent2;
        while (current != null)
        {
            Require(ancestors.Count < 64, "ancestor_depth_truncated");
            Require(!seen.Any(previous => SameObject(previous, current)), "ancestor_cycle");
            seen.Add(current);
            IComponent2 parent = current;
            int suppression = gate.Call("GetSuppression2", parent.GetSuppression2);
            Require(suppression == (int)swComponentSuppressionState_e.swComponentFullyResolved
                || suppression == (int)swComponentSuppressionState_e.swComponentResolved, "ancestor_unavailable");
            string path = gate.Call("Component.GetPathName", parent.GetPathName);
            string fullPath = gate.Call("Name2", () => parent.Name2);
            string configuration = gate.Call("ReferencedConfiguration", () => parent.ReferencedConfiguration);
            Require(!string.IsNullOrWhiteSpace(path) && !string.IsNullOrWhiteSpace(fullPath)
                && !string.IsNullOrWhiteSpace(configuration), "ancestor_unavailable");
            ancestors.Add(new AncestorState(parent, DocumentIds.For(path), fullPath, configuration));
            current = gate.Call("GetParent", parent.GetParent) as IComponent2;
        }

        // NULL normally terminates top-level/root chains; it is not a root component handle.
        return ancestors;
    }

    private static void RequireSavedOccurrence(
        ComponentInstance occurrence, EvidencePackage package, IReadOnlyList<AncestorState>? ancestors)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var savedAncestors = new List<ComponentInstance>();
        ComponentInstance? current = occurrence;
        while (current != null)
        {
            Require(seen.Count < 64 && seen.Add(current.Id) && current.Suppression == SuppressionState.Resolved,
                "saved_occurrence_unavailable");
            Document? document = package.Documents.SingleOrDefault(row => row.DocumentId == current.DocumentId);
            Require(document != null && document.Configurations.Contains(current.ReferencedConfiguration),
                "saved_configuration_unknown");
            if (current.ParentId == null)
            {
                Require(current.DocumentId == package.Design.RootAssemblyDocumentId, "saved_occurrence_unavailable");
                if (ancestors != null)
                {
                    Require(savedAncestors.Count == ancestors.Count, "ancestor_package_mismatch");
                    for (int index = 0; index < ancestors.Count; index++)
                    {
                        Require(savedAncestors[index].DocumentId == ancestors[index].DocumentId
                            && savedAncestors[index].FullPath == ancestors[index].FullPath
                            && savedAncestors[index].ReferencedConfiguration == ancestors[index].Configuration,
                            "ancestor_package_mismatch");
                    }
                }

                return;
            }

            current = package.Components.SingleOrDefault(row => row.Id == current.ParentId);
            Require(current != null, "saved_occurrence_unavailable");
            if (current!.ParentId != null)
            {
                savedAncestors.Add(current);
            }
        }
    }

    private static List<T> IdentityMatches<T>(
        IReadOnlyList<T> candidates, Func<T, string> reference, IModelDoc2 scope, string observed, SwGate gate)
    {
        // IsSamePersistentID is tri-state. The existing bool IsSame convenience deliberately
        // cannot establish uniqueness when a relevant competitor is unresolvable (-1).
        var matches = new List<T>();
        byte[] observedBytes = PersistRefCodec.Decode(observed);
        IModelDocExtension? extension = gate.Call("Extension", () => scope.Extension);
        Require(extension != null, "identity_comparison_unresolved");
        foreach (T candidate in candidates)
        {
            string saved = reference(candidate);
            Require(!string.IsNullOrWhiteSpace(saved), "identity_reference_missing");
            byte[] savedBytes;
            try
            {
                savedBytes = PersistRefCodec.Decode(saved);
            }
            catch (PersistRefError)
            {
                throw new SelectionUnresolved("identity_comparison_unresolved");
            }

            int comparison = gate.Call("IsSamePersistentID", () => extension!.IsSamePersistentID(savedBytes, observedBytes));
            Require(comparison == 0 || comparison == 1, "identity_comparison_unresolved");
            if (comparison == 1)
            {
                matches.Add(candidate);
            }
        }

        return matches;
    }

    private static bool SameTransform(double[][] first, double[][] second) =>
        first != null && second != null && first.Length == 4 && second.Length == 4
        && Enumerable.Range(0, 4).All(row => first[row] != null && second[row] != null
            && first[row].Length == 4 && second[row].Length == 4
            && Enumerable.Range(0, 4).All(column =>
                !double.IsNaN(first[row][column]) && !double.IsInfinity(first[row][column])
                && Math.Abs(first[row][column] - second[row][column]) <= 1e-9));

    private static bool SameObject(object first, object? second) =>
        second != null && (ReferenceEquals(first, second) || first.Equals(second));

    private static void RequireClean(ModelState state, string prefix)
    {
        Require(!state.Dirty, prefix + "_dirty");
        Require(state.DirtyReliable, prefix + "_dirty_unreliable");
    }

    private static void Require(bool condition, string reason)
    {
        if (!condition)
        {
            throw new SelectionUnresolved(reason);
        }
    }

    private static EngineeringSelectionObservation Unresolved(EngineeringSelectionObservation result, string reason)
    {
        result.Status = "unresolved";
        result.Kind = null;
        result.EntityId = null;
        result.ComponentId = null;
        result.DocumentId = null;
        result.Configuration = null;
        result.DisplayName = null;
        result.ReasonCodes = new[] { reason };
        return result;
    }

    private static byte[] ReadPackage(string path)
    {
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (stream.Length > MaximumPackageBytes)
        {
            throw new InvalidDataException("Saved package exceeds the selection read bound.");
        }

        using var bytes = new MemoryStream();
        stream.CopyTo(bytes);
        return bytes.ToArray();
    }

    private static string Digest(byte[] bytes)
    {
        using var sha = SHA256.Create();
        return string.Concat(sha.ComputeHash(bytes).Select(value => value.ToString("x2")));
    }

    private sealed class SelectionUnresolved : Exception
    {
        internal SelectionUnresolved(string reason) : base(reason) => Reason = reason;

        internal string Reason { get; }
    }

    private sealed class ModelState
    {
        internal ModelState(string documentId, int type, string configuration, bool dirty, bool readOnly, bool reliable)
        {
            DocumentId = documentId;
            Type = type;
            Configuration = configuration;
            Dirty = dirty;
            ReadOnly = readOnly;
            DirtyReliable = reliable;
        }

        internal string DocumentId { get; }
        internal int Type { get; }
        internal string Configuration { get; }
        internal bool Dirty { get; }
        internal bool ReadOnly { get; }
        internal bool DirtyReliable { get; }
        internal bool SameAs(ModelState other) => DocumentId == other.DocumentId && Type == other.Type
            && Configuration == other.Configuration && Dirty == other.Dirty && ReadOnly == other.ReadOnly
            && DirtyReliable == other.DirtyReliable;
    }

    private sealed class OccurrenceState
    {
        internal OccurrenceState(IModelDoc2 owner, string path, string fullPath, string configuration,
            double[][] transform, IReadOnlyList<AncestorState> ancestors)
        {
            Owner = owner;
            Path = path;
            FullPath = fullPath;
            Configuration = configuration;
            Transform = transform;
            Ancestors = ancestors;
        }

        internal IModelDoc2 Owner { get; }
        internal string Path { get; }
        internal string FullPath { get; }
        internal string Configuration { get; }
        internal double[][] Transform { get; }
        internal IReadOnlyList<AncestorState> Ancestors { get; }
        internal bool SameAs(OccurrenceState other) => SameObject(Owner, other.Owner) && Path == other.Path
            && FullPath == other.FullPath && Configuration == other.Configuration && SameTransform(Transform, other.Transform)
            && Ancestors.Count == other.Ancestors.Count
            && Enumerable.Range(0, Ancestors.Count).All(index => Ancestors[index].SameAs(other.Ancestors[index]));
    }

    private sealed class AncestorState
    {
        internal AncestorState(IComponent2 component, string documentId, string fullPath, string configuration)
        {
            Component = component;
            DocumentId = documentId;
            FullPath = fullPath;
            Configuration = configuration;
        }

        internal IComponent2 Component { get; }
        internal string DocumentId { get; }
        internal string FullPath { get; }
        internal string Configuration { get; }
        internal bool SameAs(AncestorState other) => SameObject(Component, other.Component)
            && DocumentId == other.DocumentId && FullPath == other.FullPath && Configuration == other.Configuration;
    }
}
