using System;

namespace SwReview.AddIn.Review;

/// <summary>Which call <see cref="FeatureSelection"/> chose, and therefore what to select.</summary>
public enum FeatureSelectionKind
{
    /// <summary>Nothing can be selected; <see cref="FeatureSelectionPlan.Message"/> says why.</summary>
    None,

    /// <summary>The resolved feature itself, in the active document (`IFeature.Select2`).</summary>
    Feature,

    /// <summary>
    /// The feature through its component, by name, on the active document's extension
    /// (`IModelDocExtension.SelectByID2(Name, TypeName, ...)`).
    /// </summary>
    Qualified,

    /// <summary>The component alone: the guaranteed fallback, and never a success.</summary>
    Component,
}

/// <summary>
/// What <see cref="FeatureSelection"/> is given: the shape of one Show, with no COM in it.
/// </summary>
public sealed class FeatureSelectionRequest
{
    /// <param name="activeDocumentPath">`IModelDoc2.GetPathName` of the document on screen.</param>
    /// <param name="scopeDocumentPath">The path of the document whose extension produced the
    /// persistent reference, or null when the finding named no scope.</param>
    /// <param name="componentSelectByIdString">`IComponent2.GetSelectByIDString()` for the
    /// instance the page asked about, or null when there is no component to reach through.</param>
    /// <param name="featureSelectName">The name half of
    /// `IFeature.GetNameForSelection(out type)`, or null when it could not be read.</param>
    /// <param name="featureSelectType">The type half of the same call.</param>
    /// <param name="featureName">What to call the feature in a message to the engineer.</param>
    /// <param name="isFolder">Whether the feature is a feature-tree folder, which has no
    /// geometry to zoom to.</param>
    public FeatureSelectionRequest(
        string activeDocumentPath,
        string? scopeDocumentPath,
        string? componentSelectByIdString,
        string? featureSelectName,
        string? featureSelectType,
        string? featureName,
        bool isFolder)
    {
        ActiveDocumentPath = activeDocumentPath
            ?? throw new ArgumentNullException(nameof(activeDocumentPath));
        ScopeDocumentPath = scopeDocumentPath;
        ComponentSelectByIdString = componentSelectByIdString;
        FeatureSelectName = featureSelectName;
        FeatureSelectType = featureSelectType;
        FeatureName = featureName;
        IsFolder = isFolder;
    }

    public string ActiveDocumentPath { get; }

    public string? ScopeDocumentPath { get; }

    public string? ComponentSelectByIdString { get; }

    public string? FeatureSelectName { get; }

    public string? FeatureSelectType { get; }

    public string? FeatureName { get; }

    public bool IsFolder { get; }
}

/// <summary>What to do, and what to tell the engineer if it is not everything they asked for.</summary>
public sealed class FeatureSelectionPlan
{
    internal FeatureSelectionPlan(
        FeatureSelectionKind kind, string? name, string? typeName, bool zoom, bool ok, string message)
    {
        Kind = kind;
        Name = name;
        TypeName = typeName;
        Zoom = zoom;
        Ok = ok;
        Message = message;
    }

    public FeatureSelectionKind Kind { get; }

    /// <summary>The `SelectByID2` name for <see cref="FeatureSelectionKind.Qualified"/>, the
    /// component's own select string for <see cref="FeatureSelectionKind.Component"/>, and null
    /// otherwise.</summary>
    public string? Name { get; }

    /// <summary>The `SelectByID2` type, for <see cref="FeatureSelectionKind.Qualified"/> only.</summary>
    public string? TypeName { get; }

    /// <summary>Whether to call `ViewZoomToSelection` after the selection succeeds.</summary>
    public bool Zoom { get; }

    /// <summary>Whether this plan, carried out, is the Show the engineer pressed for.</summary>
    public bool Ok { get; }

    /// <summary>What `entity.shown` carries as its message.</summary>
    public string Message { get; }
}

/// <summary>
/// What to select when a finding's subject is a feature, as a pure function.
///
/// This is defect D3's fix (plan.md). <see cref="SwEntityResolver"/> resolves the persistent
/// reference against the document whose extension produced it - which is correct - and then
/// selected on the <b>active</b> document. For a feature reached through a component that
/// selection landed in the part's own selection manager: the assembly window showed nothing,
/// the zoom was a no-op, and the engineer got no message. Feature 004 reuses the same resolver
/// for `remodel.show_change`, so the silent failure would have been inherited.
///
/// Three tiers, in the order a Show should try them:
///
/// 1. <b>The reference belongs to the document on screen.</b> Select the object already in
///    hand. Nothing composed, nothing that can be spelled wrong.
/// 2. <b>The reference belongs to a component of the document on screen.</b> Address the
///    feature through that component -
///    `&lt;feature select name&gt;@&lt;IComponent2.GetSelectByIDString()&gt;` with the type
///    `IFeature.GetNameForSelection` gave - so the selection lands in the window the engineer
///    is looking at. Both API members are verified present on the 2024 SP5 interop; whether
///    this concatenation is the right composition on 2024, and whether `GetNameForSelection`
///    on a feature taken from the part document already returns a qualified name, is PROBE-16.
/// 3. <b>Neither.</b> Select the component alone and say which feature to look for inside it,
///    or, when there is no component either, select nothing and say so. Reporting `ok: false`
///    with a sentence is the requirement (FR-027); selecting nothing and reporting success is
///    the behaviour being replaced.
///
/// A folder is selected but never zoomed to, at every tier: it has no geometry, so
/// `ViewZoomToSelection` on one either does nothing or throws the view somewhere unhelpful, and
/// an engineer watching an unchanged graphics area has no way to know the Show worked.
///
/// Pure on purpose. No COM type appears in the signature, so every branch is covered on a
/// machine with no SOLIDWORKS seat, and the resolver is left with the interop calls and nothing
/// else to get wrong.
/// </summary>
public static class FeatureSelection
{
    /// <summary>What to select for <paramref name="request"/>.</summary>
    public static FeatureSelectionPlan Plan(FeatureSelectionRequest request)
    {
        if (request == null)
        {
            throw new ArgumentNullException(nameof(request));
        }

        bool zoom = !request.IsFolder;
        string selected = request.IsFolder ? "selected in the feature tree" : "ok";

        if (InActiveDocument(request.ActiveDocumentPath, request.ScopeDocumentPath))
        {
            return new FeatureSelectionPlan(
                FeatureSelectionKind.Feature, null, null, zoom, ok: true, message: selected);
        }

        string? component = Blank(request.ComponentSelectByIdString);
        string? selectName = Blank(request.FeatureSelectName);
        string? selectType = Blank(request.FeatureSelectType);
        string feature = Blank(request.FeatureName) ?? "the feature";

        if (component != null && selectName != null && selectType != null)
        {
            return new FeatureSelectionPlan(
                FeatureSelectionKind.Qualified,
                selectName + "@" + component,
                selectType,
                zoom,
                ok: true,
                message: selected);
        }

        if (component != null)
        {
            return new FeatureSelectionPlan(
                FeatureSelectionKind.Component,
                component,
                null,
                zoom: false,
                ok: false,
                message: $"SOLIDWORKS did not name '{feature}' for selection, so its component "
                    + $"'{component}' is selected instead; look for '{feature}' in its feature tree.");
        }

        return new FeatureSelectionPlan(
            FeatureSelectionKind.None,
            null,
            null,
            zoom: false,
            ok: false,
            message: $"'{feature}' belongs to '{request.ScopeDocumentPath}', which is not the "
                + "active document, and the finding names no component instance to select it "
                + "through. Open that document and find it in the feature tree.");
    }

    /// <summary>
    /// Whether the reference's scope is the document on screen.
    ///
    /// A finding with no scope is a finding about whatever the engineer is looking at. The
    /// comparison ignores case because SOLIDWORKS and the package do not always agree on the
    /// case of a drive letter or a folder, and a mismatch there would push every Show down to
    /// tier 2 for no reason.
    ///
    /// Public because the caller asks it first, to decide whether looking a component up is
    /// worth the interop at all - and it has to be the same question <see cref="Plan"/> asks,
    /// not a second spelling of it.
    /// </summary>
    public static bool InActiveDocument(string activeDocumentPath, string? scopeDocumentPath)
    {
        if (activeDocumentPath == null)
        {
            throw new ArgumentNullException(nameof(activeDocumentPath));
        }

        string? scope = Blank(scopeDocumentPath);
        return scope == null
            || string.Equals(scope, activeDocumentPath.Trim(), StringComparison.OrdinalIgnoreCase);
    }

    private static string? Blank(string? value) =>
        string.IsNullOrWhiteSpace(value) ? null : value!.Trim();
}
