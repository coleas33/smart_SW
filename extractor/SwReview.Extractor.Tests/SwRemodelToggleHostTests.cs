using System;
using System.Linq;
using System.Reflection;
using System.Text.RegularExpressions;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.Rms;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// 004 build order, lane B: <see cref="IRemodelToggleHost"/> is mapped onto <c>ISldWorks</c> once,
/// in <see cref="SwRemodelToggleHost"/>, which the probe host and the add-in's bridge seat both
/// delegate to. Ungated, like lane A's shared classes: <see cref="RemodelSystemToggles"/> gates
/// every call from outside.
/// </summary>
public class SwRemodelToggleHostTests
{
    // ---- the shape --------------------------------------------------------------------------------

    [Fact]
    public void ItIsPublicSealedAndImplementsExactlyTheToggleHost()
    {
        Assert.True(typeof(SwRemodelToggleHost).IsPublic);
        Assert.True(typeof(SwRemodelToggleHost).IsSealed);
        Assert.Equal(new[] { typeof(IRemodelToggleHost) }, typeof(SwRemodelToggleHost).GetInterfaces());
    }

    [Fact]
    public void ItIsBuiltFromTheApplicationAlone()
    {
        ConstructorInfo constructor = Assert.Single(
            typeof(SwRemodelToggleHost).GetConstructors(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic));

        Assert.Equal(new[] { typeof(ISldWorks) }, constructor.GetParameters().Select(parameter => parameter.ParameterType));
        Assert.Equal("swApp", Assert.Throws<ArgumentNullException>(() => new SwRemodelToggleHost(null!)).ParamName);
    }

    [Fact]
    public void ItTakesAndHoldsNoGateNoGuardAndNoScopeAndNamesNone()
    {
        Assert.Empty(AdapterShape.MentionsOfForbiddenTypes(typeof(SwRemodelToggleHost)));

        string code = AdapterShape.CodeOutsideComments(ProbeWrapperCases.ProductSource("SwRemodelToggleHost.cs"));
        foreach (string token in AdapterShape.GatedCallTokens)
        {
            Assert.DoesNotContain(token, code, StringComparison.Ordinal);
        }
    }

    // ---- one interop member per interface member ---------------------------------------------------

    [Fact]
    public void ReadingAToggleAsksForExactlyThatToggle()
    {
        var application = new InteropRecorder<ISldWorks>().Answer("GetUserPreferenceToggle", true);

        Assert.True(new SwRemodelToggleHost(application.Instance).GetUserPreferenceToggle(RemodelSystemToggles.ShowErrorsEveryRebuild));

        (string member, object?[] arguments) = Assert.Single(application.Calls);
        Assert.Equal("GetUserPreferenceToggle", member);
        Assert.Equal(new object?[] { 77 }, arguments);
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void SettingAToggleWritesExactlyThatToggleAndValue(bool value)
    {
        var application = new InteropRecorder<ISldWorks>();

        new SwRemodelToggleHost(application.Instance).SetUserPreferenceToggle(RemodelSystemToggles.WarnSaveUpdateErrors, value);

        (string member, object?[] arguments) = Assert.Single(application.Calls);
        Assert.Equal("SetUserPreferenceToggle", member);
        Assert.Equal(new object?[] { 329, value }, arguments);
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void CommandInProgressIsReadAsItsPropertyGetter(bool answer)
    {
        var application = new InteropRecorder<ISldWorks>().Answer("get_CommandInProgress", answer);

        Assert.Equal(answer, new SwRemodelToggleHost(application.Instance).GetCommandInProgress());
        Assert.Equal(new[] { "get_CommandInProgress" }, application.Members);
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void CommandInProgressIsWrittenAsItsPropertySetter(bool value)
    {
        var application = new InteropRecorder<ISldWorks>();

        new SwRemodelToggleHost(application.Instance).SetCommandInProgress(value);

        (string member, object?[] arguments) = Assert.Single(application.Calls);
        Assert.Equal("set_CommandInProgress", member);
        Assert.Equal(new object?[] { value }, arguments);
    }

    /// <summary>A seat that throws is heard: the host does not swallow a failed read or write.</summary>
    [Fact]
    public void AFailureReachesTheCaller()
    {
        var application = new InteropRecorder<ISldWorks>()
            .Fail("SetUserPreferenceToggle", new InvalidOperationException("seat said no"));

        Assert.Equal(
            "seat said no",
            Assert.Throws<InvalidOperationException>(
                () => new SwRemodelToggleHost(application.Instance).SetUserPreferenceToggle(10, false)).Message);
    }

    // ---- the mapping is written once ---------------------------------------------------------------

    /// <summary>
    /// The probe host keeps no toggle mapping of its own: its four members delegate to the shared
    /// class, and it names no toggle member of <c>ISldWorks</c> on its application object.
    /// </summary>
    [Fact]
    public void TheProbeHostDelegatesItsFourToggleMembers()
    {
        string code = AdapterShape.CodeOutsideComments(ProbeWrapperCases.ProductSource("SwRemodelProbeHost.cs"));

        Assert.Single(Regex.Matches(code, @"new\s+SwRemodelToggleHost\s*\(\s*swApp\s*\)").Cast<Match>());
        Assert.Matches(@"GetUserPreferenceToggle\(int toggle\)\s*=>\s*_toggles\.GetUserPreferenceToggle\(toggle\);", code);
        Assert.Matches(@"SetUserPreferenceToggle\(int toggle, bool value\)\s*=>\s*_toggles\.SetUserPreferenceToggle\(toggle, value\);", code);
        Assert.Matches(@"GetCommandInProgress\(\)\s*=>\s*_toggles\.GetCommandInProgress\(\);", code);
        Assert.Matches(@"SetCommandInProgress\(bool value\)\s*=>\s*_toggles\.SetCommandInProgress\(value\);", code);
        Assert.DoesNotMatch(@"_swApp\s*\.\s*(GetUserPreferenceToggle|SetUserPreferenceToggle|CommandInProgress)\b", code);
    }
}
