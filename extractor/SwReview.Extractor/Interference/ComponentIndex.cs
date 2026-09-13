using System;
using System.Collections.Generic;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ids;

namespace SwReview.Extractor.Interference;

/// <summary>
/// Both directions of the component-id mapping the interference and capture paths need:
/// a live <c>IComponent2</c> to the package id the dump gave it, and a package id back to
/// the live component and its pattern.
///
/// The ids are allocated exactly as <see cref="PackageWriter"/> allocates them - traversal
/// order, prefix <c>cmp</c>, nodes without a file path skipped - so an id the Python side
/// read out of <c>package.json</c> means the same component here. That is only true while
/// the same document and configuration are open; a different assembly gives different ids,
/// which is why the bridge reports the document it attached to in every <c>ping</c>.
///
/// Handles are compared by reference identity, not by <c>GetID</c>, which collides across
/// subassemblies (research R12).
/// </summary>
public sealed class ComponentIndex
{
    private readonly Dictionary<string, InterferenceComponent> _byId =
        new Dictionary<string, InterferenceComponent>(StringComparer.Ordinal);

    private readonly List<KeyValuePair<object, string>> _byHandle =
        new List<KeyValuePair<object, string>>();

    /// <summary>
    /// The fast path. The CLR caches one RCW per COM identity per apartment, so the handle
    /// SOLIDWORKS hands back for a component is normally the same object the traversal saw;
    /// <see cref="_byHandle"/> is the fallback for when it is not.
    /// </summary>
    private readonly Dictionary<object, string> _byReference =
        new Dictionary<object, string>(ReferenceComparer.Instance);

    public ComponentIndex(ComponentTreeResult tree)
    {
        if (tree == null)
        {
            throw new ArgumentNullException(nameof(tree));
        }

        var ids = new IdAllocator("cmp");
        foreach (ComponentNode node in tree.Nodes)
        {
            if (string.IsNullOrWhiteSpace(node.DocumentPath))
            {
                // PackageWriter records a gap and skips the node; skipping it here too is
                // what keeps the id sequences identical.
                continue;
            }

            string id = ids.Next();
            _byId[id] = new InterferenceComponent(id, node.PatternId, node.Handle);

            if (node.Handle != null)
            {
                _byHandle.Add(new KeyValuePair<object, string>(node.Handle!, id));
                _byReference[node.Handle!] = id;
            }
        }
    }

    /// <summary>How many components carry an id.</summary>
    public int Count => _byId.Count;

    /// <summary>The package id for a live component, or null when the dump never saw it.</summary>
    public string? IdOf(object componentHandle)
    {
        if (componentHandle == null)
        {
            return null;
        }

        string found;
        if (_byReference.TryGetValue(componentHandle, out found))
        {
            return found;
        }

        foreach (KeyValuePair<object, string> entry in _byHandle)
        {
            // Interop can hand back a different RCW for the same underlying object; Equals
            // on an RCW compares the COM identity, which is the only correct answer here.
            if (entry.Key.Equals(componentHandle))
            {
                return entry.Value;
            }
        }

        return null;
    }

    /// <summary>Identity only: two distinct RCWs are different keys on the fast path.</summary>
    private sealed class ReferenceComparer : IEqualityComparer<object>
    {
        public static readonly ReferenceComparer Instance = new ReferenceComparer();

        public new bool Equals(object x, object y) => ReferenceEquals(x, y);

        public int GetHashCode(object obj) =>
            System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(obj);
    }

    /// <summary>The component a package id names, or null when this document has no such id.</summary>
    public InterferenceComponent? ById(string componentId)
    {
        if (string.IsNullOrWhiteSpace(componentId))
        {
            return null;
        }

        InterferenceComponent found;
        return _byId.TryGetValue(componentId, out found) ? found : null;
    }

    /// <summary>The pattern a component belongs to, for <c>group_key</c>; null when it is not patterned.</summary>
    public string? PatternOf(string componentId) => ById(componentId)?.PatternId;
}
