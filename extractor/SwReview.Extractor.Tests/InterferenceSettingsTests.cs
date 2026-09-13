using System;
using System.Collections.Generic;
using System.Linq;
using SwReview.Extractor.Interference;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Tests.Fakes;
using Xunit;
using IrInterference = SwReview.Extractor.Ir.Interference;
using IrSettings = SwReview.Extractor.Ir.InterferenceSettings;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T065. Two things an interference run must get right before any finding can be trusted:
/// the command-line flags reach the right <c>IInterferenceDetectionMgr</c> properties, and
/// the settings that were actually used are echoed into every row. "No interference found"
/// is meaningless without them (constitution Principle I).
///
/// <c>--truncate-after</c> is here too, because it is the same promise from the other side:
/// a pair that was not computed says so rather than looking clean.
/// </summary>
public class InterferenceSettingsTests
{
    // ---- the flag-to-API mapping -------------------------------------------------

    [Fact]
    public void ApplyTo_MapsEveryFlagToItsManagerProperty()
    {
        var settings = new InterferenceRunSettings
        {
            TreatCoincidentAsInterference = true,
            TreatSubassembliesAsComponents = true,
            IncludeMultibody = true,
            IgnoreHidden = true,
        };

        var manager = new RecordingManagerProperties();
        settings.ApplyTo(manager);

        Assert.True(manager.TreatCoincidenceAsInterferenceValue);
        Assert.True(manager.TreatSubAssembliesAsComponentsValue);
        Assert.True(manager.IncludeMultibodyPartInterferencesValue);
        Assert.True(manager.IgnoreHiddenBodiesValue);
    }

    [Fact]
    public void ApplyTo_DefaultsAreTheDialogDefaults()
    {
        var manager = new RecordingManagerProperties();
        new InterferenceRunSettings().ApplyTo(manager);

        Assert.False(manager.TreatCoincidenceAsInterferenceValue);
        Assert.False(manager.TreatSubAssembliesAsComponentsValue);
        Assert.False(manager.IncludeMultibodyPartInterferencesValue);
        Assert.False(manager.IgnoreHiddenBodiesValue);
    }

    [Fact]
    public void ApplyTo_FlagsAreNotSwapped()
    {
        var settings = new InterferenceRunSettings
        {
            TreatCoincidentAsInterference = true,
            IgnoreHidden = true,
        };

        var manager = new RecordingManagerProperties();
        settings.ApplyTo(manager);

        Assert.True(manager.TreatCoincidenceAsInterferenceValue);
        Assert.True(manager.IgnoreHiddenBodiesValue);
        Assert.False(manager.TreatSubAssembliesAsComponentsValue);
        Assert.False(manager.IncludeMultibodyPartInterferencesValue);
    }

    [Theory]
    [InlineData(FastenerFolderTreatment.Include)]
    [InlineData(FastenerFolderTreatment.Exclude)]
    [InlineData(FastenerFolderTreatment.Only)]
    public void ApplyTo_AlwaysCreatesTheFastenersFolder(FastenerFolderTreatment treatment)
    {
        // The folder is what fills IInterference.IsFastener; --fasteners exclude|only is a
        // filter over that flag, so turning the folder off would break both.
        var manager = new RecordingManagerProperties();
        new InterferenceRunSettings { Fasteners = treatment }.ApplyTo(manager);

        Assert.True(manager.CreateFastenersFolderValue);
    }

    [Fact]
    public void ApplyTo_NullManager_Throws()
    {
        Assert.Throws<ArgumentNullException>(() => new InterferenceRunSettings().ApplyTo(null!));
    }

    // ---- --fasteners -------------------------------------------------------------

    [Theory]
    [InlineData("include", FastenerFolderTreatment.Include)]
    [InlineData("exclude", FastenerFolderTreatment.Exclude)]
    [InlineData("only", FastenerFolderTreatment.Only)]
    [InlineData("ONLY", FastenerFolderTreatment.Only)]
    [InlineData(null, FastenerFolderTreatment.Include)]
    public void ParseFastenerTreatment_ReadsTheContractValues(string? text, FastenerFolderTreatment expected)
    {
        Assert.Equal(expected, InterferenceRunSettings.ParseFastenerTreatment(text));
    }

    [Fact]
    public void ParseFastenerTreatment_UnknownValue_Throws()
    {
        Assert.Throws<ArgumentException>(() => InterferenceRunSettings.ParseFastenerTreatment("some"));
    }

    [Fact]
    public void Keeps_ExcludeDropsFastenersAndOnlyKeepsThem()
    {
        var include = new InterferenceRunSettings { Fasteners = FastenerFolderTreatment.Include };
        var exclude = new InterferenceRunSettings { Fasteners = FastenerFolderTreatment.Exclude };
        var only = new InterferenceRunSettings { Fasteners = FastenerFolderTreatment.Only };

        Assert.True(include.Keeps(true));
        Assert.True(include.Keeps(false));
        Assert.False(exclude.Keeps(true));
        Assert.True(exclude.Keeps(false));
        Assert.True(only.Keeps(true));
        Assert.False(only.Keeps(false));
    }

    [Fact]
    public void Run_FastenersExclude_DropsFastenerResults()
    {
        var housing = new FakeComponent("cmp:0001");
        var screw = new FakeComponent("cmp:0011");
        var plate = new FakeComponent("cmp:0002");

        var results = new IInterferenceResult[]
        {
            new FakeInterferenceResult(1e-9, housing, screw) { IsFastener = true },
            new FakeInterferenceResult(2e-9, housing, plate) { IsFastener = false },
        };

        InterferenceRunResult run = Run(
            results,
            new InterferenceRunSettings { Fasteners = FastenerFolderTreatment.Exclude });

        IrInterference row = Assert.Single(run.Interferences);
        Assert.Equal(new[] { "cmp:0001", "cmp:0002" }, row.ComponentIds);
    }

    [Fact]
    public void Run_FastenersOnly_KeepsOnlyFastenerResults()
    {
        var housing = new FakeComponent("cmp:0001");
        var screw = new FakeComponent("cmp:0011");
        var plate = new FakeComponent("cmp:0002");

        var results = new IInterferenceResult[]
        {
            new FakeInterferenceResult(1e-9, housing, screw) { IsFastener = true },
            new FakeInterferenceResult(2e-9, housing, plate) { IsFastener = false },
        };

        InterferenceRunResult run = Run(
            results,
            new InterferenceRunSettings { Fasteners = FastenerFolderTreatment.Only });

        IrInterference row = Assert.Single(run.Interferences);
        Assert.True(row.IsFastener);
        Assert.Equal(new[] { "cmp:0001", "cmp:0011" }, row.ComponentIds);
    }

    // ---- the echo into the IR ----------------------------------------------------

    [Fact]
    public void Run_EchoesTheSettingsIntoEveryRow()
    {
        var settings = new InterferenceRunSettings
        {
            TreatCoincidentAsInterference = true,
            TreatSubassembliesAsComponents = true,
            IncludeMultibody = true,
            IgnoreHidden = true,
            Fasteners = FastenerFolderTreatment.Only,
        };

        var housing = new FakeComponent("cmp:0001");
        var screw = new FakeComponent("cmp:0011");
        var nut = new FakeComponent("cmp:0012");

        var results = new IInterferenceResult[]
        {
            new FakeInterferenceResult(1e-9, housing, screw) { IsFastener = true },
            new FakeInterferenceResult(2e-9, housing, nut) { IsFastener = true },
        };

        InterferenceRunResult run = Run(results, settings);

        Assert.Equal(2, run.Interferences.Count);
        foreach (IrInterference row in run.Interferences)
        {
            IrSettings echoed = row.Settings;
            Assert.True(echoed.TreatCoincidentAsInterference);
            Assert.True(echoed.TreatSubassembliesAsComponents);
            Assert.True(echoed.IncludeMultibody);
            Assert.True(echoed.IgnoreHidden);
            Assert.Equal(FastenerFolderTreatment.Only, echoed.FastenerFolderTreatment);
        }
    }

    [Fact]
    public void Run_EachRowOwnsItsSettingsObject()
    {
        var housing = new FakeComponent("cmp:0001");
        var screw = new FakeComponent("cmp:0011");
        var nut = new FakeComponent("cmp:0012");

        InterferenceRunResult run = Run(
            new IInterferenceResult[]
            {
                new FakeInterferenceResult(1e-9, housing, screw),
                new FakeInterferenceResult(2e-9, housing, nut),
            },
            new InterferenceRunSettings());

        // Aliasing one settings object across rows would let a later edit rewrite history.
        Assert.NotSame(run.Interferences[0].Settings, run.Interferences[1].Settings);
    }

    [Fact]
    public void Run_LaterEditsToTheCallersSettingsDoNotReachTheRows()
    {
        var settings = new InterferenceRunSettings { IgnoreHidden = true };
        var housing = new FakeComponent("cmp:0001");
        var screw = new FakeComponent("cmp:0011");

        InterferenceRunResult run = Run(
            new IInterferenceResult[] { new FakeInterferenceResult(1e-9, housing, screw) }, settings);

        settings.IgnoreHidden = false;

        Assert.True(Assert.Single(run.Interferences).Settings.IgnoreHidden);
    }

    [Fact]
    public void Run_EchoesTheSettingsOntoTruncatedAndFailedRowsToo()
    {
        var settings = new InterferenceRunSettings { TreatCoincidentAsInterference = true };
        var a = new FakeComponent("cmp:0001");
        var b = new FakeComponent("cmp:0002");
        var c = new FakeComponent("cmp:0003");

        var detector = new FakeInterferenceDetector(
            scope => new IInterferenceResult[] { new FakeInterferenceResult(1e-9, a, b) });

        InterferenceRunResult run = new InterferenceRunner(new FakeInterferenceSource(detector)).Run(
            "Default",
            new[]
            {
                InterferencePair.Of(a.AsPairMember(), b.AsPairMember()),
                InterferencePair.Of(a.AsPairMember(), c.AsPairMember()),
            },
            settings,
            Lookup(a, b, c),
            truncateAfter: 1);

        Assert.Equal(2, run.Interferences.Count);
        Assert.All(run.Interferences, row => Assert.True(row.Settings.TreatCoincidentAsInterference));
    }

    // ---- --truncate-after --------------------------------------------------------

    [Fact]
    public void Run_TruncateAfter_MarksTheRemainingPairsTruncated()
    {
        var a = new FakeComponent("cmp:0001");
        var b = new FakeComponent("cmp:0002");
        var c = new FakeComponent("cmp:0003");
        var d = new FakeComponent("cmp:0004");

        var detector = new FakeInterferenceDetector(
            scope => new IInterferenceResult[] { new FakeInterferenceResult(1e-9, a, b) });

        InterferenceRunResult run = new InterferenceRunner(new FakeInterferenceSource(detector)).Run(
            "Default",
            new[]
            {
                InterferencePair.Of(a.AsPairMember(), b.AsPairMember()),
                InterferencePair.Of(a.AsPairMember(), c.AsPairMember()),
                InterferencePair.Of(a.AsPairMember(), d.AsPairMember()),
            },
            new InterferenceRunSettings(),
            Lookup(a, b, c, d),
            truncateAfter: 1);

        Assert.Equal(
            new[] { InterferenceStatus.Computed, InterferenceStatus.Truncated, InterferenceStatus.Truncated },
            run.Interferences.Select(i => i.Status));
    }

    [Fact]
    public void Run_TruncatedRowsNameTheirPairAndSayWhy()
    {
        var a = new FakeComponent("cmp:0001");
        var b = new FakeComponent("cmp:0002");
        var c = new FakeComponent("cmp:0003");

        var detector = new FakeInterferenceDetector(
            scope => new IInterferenceResult[] { new FakeInterferenceResult(1e-9, a, b) });

        InterferenceRunResult run = new InterferenceRunner(new FakeInterferenceSource(detector)).Run(
            "Default",
            new[]
            {
                InterferencePair.Of(a.AsPairMember(), b.AsPairMember()),
                InterferencePair.Of(a.AsPairMember(), c.AsPairMember()),
            },
            new InterferenceRunSettings(),
            Lookup(a, b, c),
            truncateAfter: 1);

        IrInterference truncated = run.Interferences[1];
        Assert.Equal(InterferenceStatus.Truncated, truncated.Status);
        Assert.Equal(new[] { "cmp:0001", "cmp:0003" }, truncated.ComponentIds);
        Assert.Null(truncated.Volume);
        Assert.Contains("truncate-after", truncated.Error!, StringComparison.Ordinal);
    }

    [Fact]
    public void Run_TruncateAfterZero_ComputesNothing()
    {
        var a = new FakeComponent("cmp:0001");
        var b = new FakeComponent("cmp:0002");

        var detector = new FakeInterferenceDetector(
            scope => new IInterferenceResult[] { new FakeInterferenceResult(1e-9, a, b) });

        InterferenceRunResult run = new InterferenceRunner(new FakeInterferenceSource(detector)).Run(
            "Default",
            new[] { InterferencePair.Of(a.AsPairMember(), b.AsPairMember()) },
            new InterferenceRunSettings(),
            Lookup(a, b),
            truncateAfter: 0);

        Assert.Equal(InterferenceStatus.Truncated, Assert.Single(run.Interferences).Status);
    }

    [Fact]
    public void Run_TruncateAfter_CountsResultsNotPairs()
    {
        // Two results come back from a single whole-assembly pass; the limit applies to the
        // rows, so the second is truncated even though there is only one unit of work.
        var a = new FakeComponent("cmp:0001");
        var b = new FakeComponent("cmp:0002");
        var c = new FakeComponent("cmp:0003");

        var detector = new FakeInterferenceDetector(scope => new IInterferenceResult[]
        {
            new FakeInterferenceResult(1e-9, a, b),
            new FakeInterferenceResult(2e-9, a, c),
        });

        InterferenceRunResult run = new InterferenceRunner(new FakeInterferenceSource(detector)).Run(
            "Default",
            new[] { InterferencePair.WholeAssembly() },
            new InterferenceRunSettings(),
            Lookup(a, b, c),
            truncateAfter: 1);

        Assert.Equal(
            new[] { InterferenceStatus.Computed, InterferenceStatus.Truncated },
            run.Interferences.Select(i => i.Status));
        Assert.Equal(new[] { "cmp:0001", "cmp:0003" }, run.Interferences[1].ComponentIds);
    }

    [Fact]
    public void Run_NegativeTruncateAfter_Throws()
    {
        var detector = new FakeInterferenceDetector();
        Assert.Throws<ArgumentOutOfRangeException>(() =>
            new InterferenceRunner(new FakeInterferenceSource(detector)).Run(
                "Default",
                new[] { InterferencePair.WholeAssembly() },
                new InterferenceRunSettings(),
                _ => null,
                truncateAfter: -1));
    }

    // ---- helpers -----------------------------------------------------------------

    /// <summary>A whole-assembly run over one fixed set of results.</summary>
    private static InterferenceRunResult Run(
        IReadOnlyList<IInterferenceResult> results, InterferenceRunSettings settings)
    {
        var detector = new FakeInterferenceDetector(scope => results);
        return new InterferenceRunner(new FakeInterferenceSource(detector)).Run(
            "Default",
            new[] { InterferencePair.WholeAssembly() },
            settings,
            AnyComponent);
    }

    /// <summary>Component ids for the fakes in <paramref name="known"/>; null for anything else.</summary>
    internal static Func<object, string?> Lookup(params FakeComponent[] known)
    {
        var byHandle = new Dictionary<object, string>();
        foreach (FakeComponent component in known)
        {
            byHandle[component] = component.Id;
        }

        return handle => byHandle.TryGetValue(handle, out string id) ? id : null;
    }

    /// <summary>Any <see cref="FakeComponent"/> knows its own id.</summary>
    internal static string? AnyComponent(object handle) => (handle as FakeComponent)?.Id;
}
