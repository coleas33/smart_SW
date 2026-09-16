using System;
using SwReview.AddIn.Review;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T078: the selection strategy, as a pure function.
///
/// Defect D3 (plan.md): Show selects nothing when the part is reached through a component.
/// <c>SwEntityResolver.Show</c> resolves the persistent reference against the scope document,
/// which is right, and then calls <c>ClearSelection2</c>, <c>Select2</c> and
/// <c>ViewZoomToSelection</c> on the <b>active</b> document. For a feature reached through a
/// component the selection lands in the part's own selection manager, the assembly window shows
/// nothing and the zoom is a no-op. The engineer presses Show and nothing happens, with no
/// message to act on - the worst kind of failure, and the one feature 004 would inherit
/// unchanged through `remodel.show_change`.
///
/// The fix is this class: what to select is decided as a pure function of the scope document,
/// the active document, the component and the names SOLIDWORKS gave for them, so every branch
/// is covered on a machine with no seat, and <see cref="SwEntityResolver"/> is left with
/// nothing but the interop calls the plan names (FR-027).
///
/// No COM type appears in the signature on purpose. The two API facts the strategy composes -
/// <c>IFeature.GetNameForSelection(out string type)</c> and
/// <c>IComponent2.GetSelectByIDString()</c> - are verified present on the 2024 SP5 interop;
/// whether the concatenation is the right composition on 2024, and whether
/// <c>GetNameForSelection</c> on a feature taken from the part document already returns a
/// qualified name, is PROBE-16 on the workstation. That is exactly why the composition is
/// here, behind a test, rather than inline in an interop method nobody can run headless.
/// </summary>
public sealed class FeatureSelectionTests
{
    private const string Assembly = @"C:\parts\bracket assy.SLDASM";
    private const string Part = @"C:\parts\bracket.SLDPRT";

    /// <summary>What `IComponent2.GetSelectByIDString()` hands back for one instance.</summary>
    private const string Instance = "bracket-3@bracket assy";

    // ---- the scope document is the active document --------------------------------------

    [Fact]
    public void AFeatureInTheActiveDocumentIsSelectedDirectlyAndZoomedTo()
    {
        FeatureSelectionPlan plan = FeatureSelection.Plan(new FeatureSelectionRequest(
            activeDocumentPath: Part,
            scopeDocumentPath: Part,
            componentSelectByIdString: null,
            featureSelectName: "Cut-Extrude1",
            featureSelectType: "BODYFEATURE",
            featureName: "Cut-Extrude1",
            isFolder: false));

        Assert.Equal(FeatureSelectionKind.Feature, plan.Kind);
        Assert.True(plan.Ok);
        Assert.True(plan.Zoom);
        Assert.Null(plan.Name);
        Assert.Null(plan.TypeName);
    }

    /// <summary>
    /// The part opened alone is the tab's headline case, and the finding still names the
    /// component instance the census walked. A scope that is the active document wins over a
    /// component that happens to be named: `Select2` on the object already in hand cannot be
    /// wrong, and composing a name for it could be.
    /// </summary>
    [Fact]
    public void AComponentIdIsIgnoredWhenTheScopeDocumentIsAlreadyTheActiveDocument()
    {
        FeatureSelectionPlan plan = FeatureSelection.Plan(new FeatureSelectionRequest(
            activeDocumentPath: Part,
            scopeDocumentPath: Part,
            componentSelectByIdString: Instance,
            featureSelectName: "Cut-Extrude1",
            featureSelectType: "BODYFEATURE",
            featureName: "Cut-Extrude1",
            isFolder: false));

        Assert.Equal(FeatureSelectionKind.Feature, plan.Kind);
        Assert.True(plan.Ok);
    }

    /// <summary>
    /// A finding with no scope is a finding about the document in front of the engineer. The
    /// comparison is case-insensitive because SOLIDWORKS and the package do not always agree
    /// on the case of a drive letter or a folder.
    /// </summary>
    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData(@"c:\PARTS\BRACKET.sldprt")]
    public void NoScopeOrTheSamePathInAnotherCaseIsTheActiveDocument(string? scope)
    {
        FeatureSelectionPlan plan = FeatureSelection.Plan(new FeatureSelectionRequest(
            activeDocumentPath: Part,
            scopeDocumentPath: scope,
            componentSelectByIdString: null,
            featureSelectName: "Cut-Extrude1",
            featureSelectType: "BODYFEATURE",
            featureName: "Cut-Extrude1",
            isFolder: false));

        Assert.Equal(FeatureSelectionKind.Feature, plan.Kind);
        Assert.True(plan.Ok);
    }

    // ---- the scope document is a component of the active document -----------------------

    [Fact]
    public void AFeatureInAnotherDocumentIsSelectedThroughTheComponentOnTheActiveDocument()
    {
        FeatureSelectionPlan plan = FeatureSelection.Plan(new FeatureSelectionRequest(
            activeDocumentPath: Assembly,
            scopeDocumentPath: Part,
            componentSelectByIdString: Instance,
            featureSelectName: "Cut-Extrude1",
            featureSelectType: "BODYFEATURE",
            featureName: "Cut-Extrude1",
            isFolder: false));

        Assert.Equal(FeatureSelectionKind.Qualified, plan.Kind);
        Assert.Equal("Cut-Extrude1@" + Instance, plan.Name);
        Assert.Equal("BODYFEATURE", plan.TypeName);
        Assert.True(plan.Ok);
        Assert.True(plan.Zoom);
    }

    /// <summary>
    /// The same feature in two instances of the same part is two different selections, and the
    /// only thing that distinguishes them is the component the caller named. The page holds the
    /// finding's `component_ids` and sends one of them with `entity.show`; cycling through them
    /// and labelling the button "Show (instance 1 of N)" is the page's job, and this is what
    /// makes it work - each id composes a different name.
    /// </summary>
    [Fact]
    public void TheSameFeatureInTwoInstancesIsAddressedThroughWhicheverComponentTheCallerNamed()
    {
        FeatureSelectionPlan first = FeatureSelection.Plan(Through("bracket-1@bracket assy"));
        FeatureSelectionPlan second = FeatureSelection.Plan(Through("bracket-3@bracket assy"));

        Assert.Equal("Cut-Extrude1@bracket-1@bracket assy", first.Name);
        Assert.Equal("Cut-Extrude1@bracket-3@bracket assy", second.Name);
        Assert.NotEqual(first.Name, second.Name);
    }

    // ---- the fallbacks ------------------------------------------------------------------

    /// <summary>
    /// The guaranteed path. If the feature cannot be named for selection - no
    /// <c>GetNameForSelection</c>, or a type SOLIDWORKS will not answer for - the component is
    /// selected instead and the answer says which feature to look for inside it. Selecting
    /// nothing and reporting success is the behaviour this replaces (FR-027).
    /// </summary>
    [Theory]
    [InlineData(null, "BODYFEATURE")]
    [InlineData("", "BODYFEATURE")]
    [InlineData("   ", "BODYFEATURE")]
    [InlineData("Cut-Extrude1", null)]
    [InlineData("Cut-Extrude1", "")]
    public void AFeatureThatCannotBeNamedFallsBackToTheComponentAndSaysSo(
        string? selectName, string? selectType)
    {
        FeatureSelectionPlan plan = FeatureSelection.Plan(new FeatureSelectionRequest(
            activeDocumentPath: Assembly,
            scopeDocumentPath: Part,
            componentSelectByIdString: Instance,
            featureSelectName: selectName,
            featureSelectType: selectType,
            featureName: "Cut-Extrude1",
            isFolder: false));

        Assert.Equal(FeatureSelectionKind.Component, plan.Kind);
        Assert.False(plan.Ok);
        Assert.Equal(Instance, plan.Name);
        Assert.Contains("Cut-Extrude1", plan.Message);
    }

    /// <summary>
    /// Nothing to select through and nothing safe to select: the reference belongs to a
    /// document that is not on screen, and selecting the feature in its own window would be
    /// the D3 silent failure again. The answer names the feature and the document so the
    /// engineer can open it (spec Edge Cases, SC-007).
    /// </summary>
    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("  ")]
    public void AFeatureInAnotherDocumentWithNoComponentToReachItThroughIsReportedNotSelected(
        string? component)
    {
        FeatureSelectionPlan plan = FeatureSelection.Plan(new FeatureSelectionRequest(
            activeDocumentPath: Assembly,
            scopeDocumentPath: Part,
            componentSelectByIdString: component,
            featureSelectName: "Cut-Extrude1",
            featureSelectType: "BODYFEATURE",
            featureName: "Cut-Extrude1",
            isFolder: false));

        Assert.Equal(FeatureSelectionKind.None, plan.Kind);
        Assert.False(plan.Ok);
        Assert.False(plan.Zoom);
        Assert.Contains("Cut-Extrude1", plan.Message);
        Assert.Contains("bracket.SLDPRT", plan.Message);
    }

    // ---- folders ------------------------------------------------------------------------

    /// <summary>
    /// A folder has no geometry, so <c>ViewZoomToSelection</c> on one either does nothing or
    /// throws the view somewhere unhelpful. It is selected in the tree and the answer says
    /// that is what happened, rather than leaving the engineer looking at the graphics area for
    /// a highlight that was never coming.
    /// </summary>
    [Fact]
    public void AFolderIsSelectedWithoutZoomingAndTheAnswerSaysWhereToLook()
    {
        FeatureSelectionPlan plan = FeatureSelection.Plan(new FeatureSelectionRequest(
            activeDocumentPath: Part,
            scopeDocumentPath: Part,
            componentSelectByIdString: null,
            featureSelectName: "3-Core",
            featureSelectType: "FTRFOLDER",
            featureName: "3-Core",
            isFolder: true));

        Assert.Equal(FeatureSelectionKind.Feature, plan.Kind);
        Assert.True(plan.Ok);
        Assert.False(plan.Zoom);
        Assert.Equal("selected in the feature tree", plan.Message);
    }

    [Fact]
    public void AFolderInAnotherDocumentIsAlsoSelectedThroughTheComponentWithoutZooming()
    {
        FeatureSelectionPlan plan = FeatureSelection.Plan(new FeatureSelectionRequest(
            activeDocumentPath: Assembly,
            scopeDocumentPath: Part,
            componentSelectByIdString: Instance,
            featureSelectName: "3-Core",
            featureSelectType: "FTRFOLDER",
            featureName: "3-Core",
            isFolder: true));

        Assert.Equal(FeatureSelectionKind.Qualified, plan.Kind);
        Assert.Equal("3-Core@" + Instance, plan.Name);
        Assert.False(plan.Zoom);
        Assert.True(plan.Ok);
        Assert.Equal("selected in the feature tree", plan.Message);
    }

    // ---- the strategy decides nothing it was not given ----------------------------------

    [Fact]
    public void ANullRequestIsARefusalRatherThanANullReference()
    {
        Assert.Throws<ArgumentNullException>(() => FeatureSelection.Plan(null!));
    }

    [Fact]
    public void AnActiveDocumentPathIsRequiredBecauseThereIsNoDefaultForIt()
    {
        Assert.Throws<ArgumentNullException>(() => new FeatureSelectionRequest(
            activeDocumentPath: null!,
            scopeDocumentPath: null,
            componentSelectByIdString: null,
            featureSelectName: null,
            featureSelectType: null,
            featureName: null,
            isFolder: false));
    }

    private static FeatureSelectionRequest Through(string component) =>
        new FeatureSelectionRequest(
            activeDocumentPath: Assembly,
            scopeDocumentPath: Part,
            componentSelectByIdString: component,
            featureSelectName: "Cut-Extrude1",
            featureSelectType: "BODYFEATURE",
            featureName: "Cut-Extrude1",
            isFolder: false);
}
