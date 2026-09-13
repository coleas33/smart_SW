using System;
using System.Collections.Generic;
using System.Globalization;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Ir;
using IrInterference = SwReview.Extractor.Ir.Interference;

namespace SwReview.Extractor.Interference;

/// <summary>
/// T069. Runs SOLIDWORKS interference detection and turns the results into IR rows.
///
/// It touches no interop: <see cref="IInterferenceSource"/> is the seam, so settings
/// mapping, the fastener filter, truncation, grouping and failure handling are unit tested
/// with a fake detector (constitution Principle III).
///
/// Three rules the reviewer depends on:
///
///   * A pair that could not be computed is still a row, with status <c>failed</c> or
///     <c>truncated</c> and a gap beside it. A missing row would read as "no interference
///     here", which is exactly the silent pass Principle I forbids.
///   * <c>group_key</c> is the pattern id of each member where it has one, else its
///     component id, sorted. Six instances of one screw pattern against the same housing
///     therefore share a key and collapse into one finding (FR-011).
///   * <c>Volume</c> is recorded as m³ with a gap saying the unit is assumed, until
///     <see cref="VolumeUnitVerified"/> is flipped by the workstation check in T069.
/// </summary>
public sealed class InterferenceRunner
{
    /// <summary>
    /// Flip to true only after the workstation check in T069 has compared
    /// <c>IInterference.Volume</c> against a known box overlap and the unit below is the
    /// one measured. Until then every run carries <see cref="VolumeUnitGapReason"/>.
    /// </summary>
    public const bool VolumeUnitVerified = false;

    /// <summary>The unit the runner records, assumed until <see cref="VolumeUnitVerified"/>.</summary>
    public const VolumeUnit AssumedVolumeUnit = VolumeUnit.M3;

    /// <summary><c>Gap.entity_kind</c> for the unverified-unit gap.</summary>
    public const string VolumeUnitGapEntityKind = "interference_volume_unit";

    /// <summary><c>Gap.reason</c> for the unverified-unit gap.</summary>
    public const string VolumeUnitGapReason =
        "IInterference.Volume unit assumed m3; verify on workstation";

    /// <summary><c>Gap.entity_kind</c> for everything else this runner records.</summary>
    public const string GapEntityKind = "interference";

    /// <summary>Id prefix for <c>Interference.id</c>.</summary>
    public const string IdPrefix = "int";

    /// <summary>
    /// What <c>component_ids</c> carries on a whole-assembly run that failed before any
    /// component was named. The IR schema needs exactly two ids, and inventing component
    /// ids would be worse than saying "everything": this row means "the whole assembly was
    /// not checked", and the gap beside it says why.
    /// </summary>
    public const string WholeAssemblyComponentId = "*";

    private readonly IInterferenceSource _source;

    public InterferenceRunner(IInterferenceSource source)
    {
        _source = source ?? throw new ArgumentNullException(nameof(source));
    }

    /// <summary>
    /// Runs detection for every pair.
    /// </summary>
    /// <param name="configuration">Active configuration name, echoed into every row.</param>
    /// <param name="pairs">
    /// The pairs from <c>--pairs</c>. A single <see cref="InterferencePair.WholeAssembly"/>
    /// is <c>--pairs all</c>.
    /// </param>
    /// <param name="settings">Applied to the manager and echoed into every row.</param>
    /// <param name="componentIdLookup">
    /// Live <c>IComponent2</c> to the package's component id, normally the dumped tree. A
    /// component the dump never saw returns null, which is a gap rather than a guess.
    /// </param>
    /// <param name="patternIdLookup">
    /// Component id to pattern id, for <c>group_key</c>. Optional: in pair mode the pair
    /// already carries its pattern ids.
    /// </param>
    /// <param name="truncateAfter">
    /// Stop computing after this many rows and mark the rest <c>truncated</c>. The test
    /// hook from contracts/cli.md; null means no limit.
    /// </param>
    public InterferenceRunResult Run(
        string configuration,
        IReadOnlyList<InterferencePair> pairs,
        InterferenceRunSettings settings,
        Func<object, string?> componentIdLookup,
        Func<string, string?>? patternIdLookup = null,
        int? truncateAfter = null)
    {
        if (pairs == null)
        {
            throw new ArgumentNullException(nameof(pairs));
        }

        if (settings == null)
        {
            throw new ArgumentNullException(nameof(settings));
        }

        if (componentIdLookup == null)
        {
            throw new ArgumentNullException(nameof(componentIdLookup));
        }

        if (truncateAfter.HasValue && truncateAfter.Value < 0)
        {
            throw new ArgumentOutOfRangeException(
                nameof(truncateAfter), truncateAfter, "--truncate-after cannot be negative.");
        }

        var state = new RunState(configuration ?? string.Empty, settings.Clone(), truncateAfter);

        IInterferenceDetector detector;
        try
        {
            detector = _source.Open();
        }
        catch (Exception error) when (!IsFatal(error))
        {
            // No manager means no pair can be answered. Every pair becomes a failed row so
            // the reviewer sees unresolved coverage for each, not an empty interference list.
            state.Gaps.Record(
                GapEntityKind, null, "open the assembly's interference detection manager", error);
            foreach (InterferencePair pair in pairs)
            {
                state.Add(Failed(state, pair, error));
            }

            return state.ToResult();
        }

        try
        {
            if (!state.Gaps.TryStep(
                GapEntityKind, null, "apply the interference detection settings", () => detector.Configure(state.Settings)))
            {
                // Detection with unknown settings would be reported against settings that
                // were never applied, so nothing is computed.
                foreach (InterferencePair pair in pairs)
                {
                    state.Add(Failed(state, pair, "the interference detection settings could not be applied"));
                }

                return state.ToResult();
            }

            foreach (InterferencePair pair in pairs)
            {
                RunPair(detector, state, pair, componentIdLookup, patternIdLookup);
            }
        }
        finally
        {
            // Done() releases the manager's temporary bodies and the fasteners folder. It
            // runs even when a pair threw, and its own failure is a gap, never an exception
            // that would hide the pair failure that caused it (research R12, T069).
            try
            {
                detector.Done();
            }
            catch (Exception error) when (!IsFatal(error))
            {
                state.Gaps.Record(
                    GapEntityKind, null, "close the interference detection manager (Done)", error);
            }
        }

        return state.ToResult();
    }

    private void RunPair(
        IInterferenceDetector detector,
        RunState state,
        InterferencePair pair,
        Func<object, string?> componentIdLookup,
        Func<string, string?>? patternIdLookup)
    {
        if (state.IsTruncated)
        {
            // The pair was never run, so the row carries the pair's own component ids.
            state.Add(Truncated(state, pair, componentIds: null, groupKey: GroupKey(pair)));
            return;
        }

        IReadOnlyList<IInterferenceResult>? found;
        try
        {
            detector.Scope(pair.Handles);
            int count = detector.GetInterferenceCount();
            found = count > 0 ? detector.GetInterferences() : new IInterferenceResult[0];
        }
        catch (Exception error) when (!IsFatal(error))
        {
            state.Gaps.Record(GapEntityKind, null, "detect interferences for " + pair.Describe(), error);
            state.Add(Failed(state, pair, error));
            return;
        }

        if (found == null)
        {
            // GetInterferences returning nothing after a non-zero count is a SOLIDWORKS
            // answer we cannot interpret, so it is a failure rather than "none found".
            state.Gaps.Add(
                GapKind.ToolError,
                GapEntityKind,
                null,
                "detect interferences for " + pair.Describe(),
                "GetInterferences returned nothing after a non-zero GetInterferenceCount.");
            state.Add(Failed(state, pair, "GetInterferences returned nothing"));
            return;
        }

        foreach (IInterferenceResult result in found)
        {
            RunResult(state, pair, result, componentIdLookup, patternIdLookup);
        }
    }

    private void RunResult(
        RunState state,
        InterferencePair pair,
        IInterferenceResult result,
        Func<object, string?> componentIdLookup,
        Func<string, string?>? patternIdLookup)
    {
        List<string>? componentIds;
        try
        {
            componentIds = ComponentIds(state, pair, result, componentIdLookup);
        }
        catch (Exception error) when (!IsFatal(error))
        {
            state.Gaps.Record(GapEntityKind, null, "read the components of an interference", error);
            state.Add(Failed(state, pair, error));
            return;
        }

        if (componentIds == null)
        {
            // The gap is already recorded; without two component ids the row could not name
            // what interferes, and the schema requires exactly two.
            return;
        }

        string groupKey = GroupKey(componentIds, pair, patternIdLookup);

        if (state.IsTruncated)
        {
            // The components are read even past the limit - that is one cheap call - because
            // a truncated row that cannot say WHICH pair was skipped is of no use to the
            // engineer. The volume and the flags, which is where the cost is, are not.
            state.Add(Truncated(state, pair, componentIds, groupKey));
            return;
        }

        double volume;
        bool isFastener;
        bool isPossible;
        try
        {
            volume = result.Volume;
            isFastener = result.IsFastener;
            isPossible = result.IsPossibleInterference;
        }
        catch (Exception error) when (!IsFatal(error))
        {
            state.Gaps.Record(
                GapEntityKind, null, "read the volume and flags of an interference", error);
            state.Add(Failed(state, pair, error, componentIds, groupKey));
            return;
        }

        if (!state.Settings.Keeps(isFastener))
        {
            // Filtered out by --fasteners, which the IR echoes, so this is not a gap.
            return;
        }

        state.RecordedVolume = true;
        state.Add(new IrInterference
        {
            Id = state.Ids.Next(),
            Configuration = state.Configuration,
            ComponentIds = componentIds,
            Volume = new Volume(volume, AssumedVolumeUnit),
            Settings = state.Settings.ToIr(),
            IsFastener = isFastener,
            IsPossible = isPossible,
            Status = InterferenceStatus.Computed,
            Error = null,
            GroupKey = groupKey,
        });
        state.Computed++;
    }

    /// <summary>
    /// The two component ids for a result, or null (with a gap recorded) when they cannot
    /// be established. Falls back to the requested pair when SOLIDWORKS named components
    /// the dump never saw, which is the normal case for a lightweight subassembly.
    /// </summary>
    private static List<string>? ComponentIds(
        RunState state,
        InterferencePair pair,
        IInterferenceResult result,
        Func<object, string?> componentIdLookup)
    {
        var ids = new List<string>(2);
        IReadOnlyList<object> components = result.Components ?? new object[0];
        int unmapped = 0;

        foreach (object component in components)
        {
            string? id = component == null ? null : componentIdLookup(component);
            if (string.IsNullOrEmpty(id))
            {
                unmapped++;
                continue;
            }

            if (!ids.Contains(id!))
            {
                ids.Add(id!);
            }
        }

        if (ids.Count == 2)
        {
            return ids;
        }

        if (!pair.IsWholeAssembly)
        {
            return new List<string> { pair.First!.Id, pair.Second!.Id };
        }

        state.Gaps.Add(
            GapKind.NotExtracted,
            GapEntityKind,
            null,
            "name the two components of an interference found in " + pair.Describe(),
            $"IInterference.Components gave {components.Count} component(s), "
            + $"{unmapped} of which are not in the dumped tree; "
            + "the IR needs exactly two component ids.");
        return null;
    }

    /// <summary>The key for a pair that was never run: pattern ids where known, else ids.</summary>
    private static string GroupKey(InterferencePair pair)
    {
        if (pair.IsWholeAssembly)
        {
            return "all";
        }

        return Join(pair.First!.GroupMember, pair.Second!.GroupMember);
    }

    /// <summary>
    /// The key for a computed result. Each member contributes its pattern id when it has
    /// one and its component id otherwise, sorted ordinally so the key does not depend on
    /// the order SOLIDWORKS listed the components in.
    /// </summary>
    private static string GroupKey(
        IReadOnlyList<string> componentIds, InterferencePair pair, Func<string, string?>? patternIdLookup)
    {
        var members = new List<string>(componentIds.Count);
        foreach (string id in componentIds)
        {
            members.Add(PatternOf(id, pair, patternIdLookup) ?? id);
        }

        members.Sort(StringComparer.Ordinal);
        return string.Join("|", members.ToArray());
    }

    private static string? PatternOf(string componentId, InterferencePair pair, Func<string, string?>? lookup)
    {
        string? fromLookup = lookup == null ? null : lookup(componentId);
        if (!string.IsNullOrEmpty(fromLookup))
        {
            return fromLookup;
        }

        if (pair.First != null && pair.First.Id == componentId)
        {
            return pair.First.PatternId;
        }

        if (pair.Second != null && pair.Second.Id == componentId)
        {
            return pair.Second.PatternId;
        }

        return null;
    }

    private static string Join(string first, string second)
    {
        var members = new[] { first, second };
        Array.Sort(members, StringComparer.Ordinal);
        return string.Join("|", members);
    }

    private static IrInterference Truncated(
        RunState state, InterferencePair pair, IReadOnlyList<string>? componentIds, string groupKey)
    {
        return new IrInterference
        {
            Id = state.Ids.Next(),
            Configuration = state.Configuration,
            ComponentIds = ComponentIdsOrPair(componentIds, pair),
            Volume = null,
            Settings = state.Settings.ToIr(),
            IsFastener = false,
            IsPossible = false,
            Status = InterferenceStatus.Truncated,
            Error = string.Format(
                CultureInfo.InvariantCulture,
                "Stopped after --truncate-after {0}; this pair was not computed.",
                state.TruncateAfter),
            GroupKey = groupKey,
        };
    }

    private static IrInterference Failed(RunState state, InterferencePair pair, Exception error) =>
        Failed(state, pair, error.GetType().Name + ": " + error.Message, null, null);

    private static IrInterference Failed(RunState state, InterferencePair pair, string message) =>
        Failed(state, pair, message, null, null);

    private static IrInterference Failed(
        RunState state,
        InterferencePair pair,
        Exception error,
        IReadOnlyList<string>? componentIds,
        string? groupKey) =>
        Failed(state, pair, error.GetType().Name + ": " + error.Message, componentIds, groupKey);

    private static IrInterference Failed(
        RunState state,
        InterferencePair pair,
        string message,
        IReadOnlyList<string>? componentIds,
        string? groupKey)
    {
        return new IrInterference
        {
            Id = state.Ids.Next(),
            Configuration = state.Configuration,
            ComponentIds = ComponentIdsOrPair(componentIds, pair),
            Volume = null,
            Settings = state.Settings.ToIr(),
            IsFastener = false,
            IsPossible = false,
            Status = InterferenceStatus.Failed,
            Error = message,
            GroupKey = groupKey ?? GroupKey(pair),
        };
    }

    /// <summary>
    /// The schema needs exactly two component ids. A whole-assembly pair that failed before
    /// any component was named has none, so the row carries
    /// <see cref="WholeAssemblyComponentId"/> rather than inventing ids that would dangle.
    /// </summary>
    private static List<string> ComponentIdsOrPair(IReadOnlyList<string>? componentIds, InterferencePair pair)
    {
        if (componentIds != null && componentIds.Count == 2)
        {
            return new List<string>(componentIds);
        }

        if (!pair.IsWholeAssembly)
        {
            return new List<string> { pair.First!.Id, pair.Second!.Id };
        }

        return new List<string> { WholeAssemblyComponentId, WholeAssemblyComponentId };
    }

    /// <summary>
    /// A dead session (<see cref="CircuitOpenError"/>) and our own bug
    /// (<see cref="MutatingCallError"/>) are never turned into a gap: the first would
    /// produce one identical row per remaining pair, and the second means the read-only
    /// guard refused a call we should not have made (see <see cref="GapCollector"/>).
    /// </summary>
    private static bool IsFatal(Exception error) =>
        error is CircuitOpenError || error is MutatingCallError;

    /// <summary>Mutable bookkeeping for one run, so the methods above stay readable.</summary>
    private sealed class RunState
    {
        public RunState(string configuration, InterferenceRunSettings settings, int? truncateAfter)
        {
            Configuration = configuration;
            Settings = settings;
            TruncateAfter = truncateAfter;
        }

        public string Configuration { get; }

        public InterferenceRunSettings Settings { get; }

        public int? TruncateAfter { get; }

        public IdAllocator Ids { get; } = new IdAllocator(IdPrefix);

        public GapCollector Gaps { get; } = new GapCollector();

        public List<IrInterference> Interferences { get; } = new List<IrInterference>();

        /// <summary>How many rows have been computed; only these count against the limit.</summary>
        public int Computed { get; set; }

        /// <summary>True once at least one volume was recorded, which is what the unit gap is about.</summary>
        public bool RecordedVolume { get; set; }

        public bool IsTruncated => TruncateAfter.HasValue && Computed >= TruncateAfter.Value;

        public void Add(IrInterference interference) => Interferences.Add(interference);

        public InterferenceRunResult ToResult()
        {
            // One gap per run, not one per result: the unit is a property of the API, not of
            // any single interference.
            if (RecordedVolume && !VolumeUnitVerified)
            {
                Gaps.Add(
                    GapKind.Unsupported,
                    VolumeUnitGapEntityKind,
                    null,
                    VolumeUnitGapReason,
                    null);
            }

            return new InterferenceRunResult(Interferences, Gaps.Gaps);
        }
    }
}
