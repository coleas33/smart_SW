using System;
using System.Collections.Generic;
using SwReview.Extractor.Ir;
using IrInterference = SwReview.Extractor.Ir.Interference;

namespace SwReview.Extractor.Interference;

/// <summary>
/// One member of a requested pair: the component id the package gave it, the pattern it
/// belongs to (if any), and the live <c>IComponent2</c> the detector must select to scope
/// detection to this component.
/// </summary>
public sealed class InterferenceComponent
{
    public InterferenceComponent(string id, string? patternId = null, object? handle = null)
    {
        if (string.IsNullOrWhiteSpace(id))
        {
            throw new ArgumentException("A component id is required.", nameof(id));
        }

        Id = id;
        PatternId = patternId;
        Handle = handle;
    }

    /// <summary>Package id, e.g. <c>cmp:0011</c>.</summary>
    public string Id { get; }

    /// <summary>
    /// The component pattern feature this instance belongs to, e.g. <c>pat:screws</c>, or
    /// null. Six instances of one pattern share a <c>group_key</c> so they collapse into a
    /// single finding (FR-011).
    /// </summary>
    public string? PatternId { get; }

    /// <summary>The live <c>IComponent2</c>, or null in tests.</summary>
    public object? Handle { get; }

    /// <summary>What this member contributes to a <c>group_key</c>: its pattern, else itself.</summary>
    public string GroupMember => PatternId ?? Id;
}

/// <summary>
/// One unit of work for <see cref="InterferenceRunner"/>: a named pair, or the whole
/// assembly (<c>--pairs all</c>), which SOLIDWORKS answers in one detection pass.
/// </summary>
public sealed class InterferencePair
{
    private static readonly object[] NoHandles = new object[0];

    private InterferencePair(InterferenceComponent? first, InterferenceComponent? second)
    {
        First = first;
        Second = second;
    }

    /// <summary>Every component against every other; the detector is left unscoped.</summary>
    public static InterferencePair WholeAssembly() => new InterferencePair(null, null);

    /// <summary>One named pair; the detector is scoped to these two components.</summary>
    public static InterferencePair Of(InterferenceComponent first, InterferenceComponent second)
    {
        if (first == null)
        {
            throw new ArgumentNullException(nameof(first));
        }

        if (second == null)
        {
            throw new ArgumentNullException(nameof(second));
        }

        return new InterferencePair(first, second);
    }

    public InterferenceComponent? First { get; }

    public InterferenceComponent? Second { get; }

    public bool IsWholeAssembly => First == null || Second == null;

    /// <summary>A sentence for a gap or an error message.</summary>
    public string Describe() => IsWholeAssembly
        ? "the whole assembly"
        : First!.Id + " and " + Second!.Id;

    /// <summary>The component handles detection should be scoped to; empty for the whole assembly.</summary>
    public IReadOnlyList<object> Handles
    {
        get
        {
            if (IsWholeAssembly || First!.Handle == null || Second!.Handle == null)
            {
                return NoHandles;
            }

            return new[] { First.Handle!, Second.Handle! };
        }
    }
}

/// <summary>One row of <c>IInterferenceDetectionMgr.GetInterferences</c>.</summary>
public interface IInterferenceResult
{
    /// <summary>
    /// <c>IInterference.Volume</c>. The unit is undocumented (research R12); the runner
    /// records m³ and a gap until <see cref="InterferenceRunner.VolumeUnitVerified"/> flips.
    /// </summary>
    double Volume { get; }

    /// <summary>The live <c>IComponent2</c> objects this result names.</summary>
    IReadOnlyList<object> Components { get; }

    /// <summary>SOLIDWORKS put the pair in the fasteners folder.</summary>
    bool IsFastener { get; }

    /// <summary>Coincident or touching rather than overlapping.</summary>
    bool IsPossibleInterference { get; }
}

/// <summary>
/// The <c>IInterferenceDetectionMgr</c> surface the runner uses, as an interface so the
/// orchestration - settings, filtering, truncation, grouping, failure handling - is unit
/// tested with a fake on a machine with no SOLIDWORKS seat (constitution Principle III).
/// </summary>
public interface IInterferenceDetector
{
    /// <summary>Applies the run's settings to the manager's properties.</summary>
    void Configure(InterferenceRunSettings settings);

    /// <summary>
    /// Scopes the next detection to <paramref name="componentHandles"/> by selecting them;
    /// an empty list clears the selection and checks the whole assembly. The manager has no
    /// scope property - it reads the selection (research R12).
    /// </summary>
    void Scope(IReadOnlyList<object> componentHandles);

    /// <summary><c>GetInterferenceCount</c>. This is the call that actually runs detection.</summary>
    int GetInterferenceCount();

    /// <summary><c>GetInterferences</c>, after <see cref="GetInterferenceCount"/>.</summary>
    IReadOnlyList<IInterferenceResult> GetInterferences();

    /// <summary><c>Done()</c>. Always called, in a finally.</summary>
    void Done();
}

/// <summary>Hands out the assembly's detector. The real one wraps <c>IAssemblyDoc</c>.</summary>
public interface IInterferenceSource
{
    /// <summary><c>IAssemblyDoc.InterferenceDetectionManager</c>.</summary>
    IInterferenceDetector Open();
}

/// <summary>What one interference run produced: the IR rows and everything it could not do.</summary>
public sealed class InterferenceRunResult
{
    public InterferenceRunResult(IReadOnlyList<IrInterference> interferences, IReadOnlyList<Gap> gaps)
    {
        Interferences = interferences ?? throw new ArgumentNullException(nameof(interferences));
        Gaps = gaps ?? throw new ArgumentNullException(nameof(gaps));
    }

    /// <summary>Appended to <c>package.json</c>'s <c>interferences</c>, in run order.</summary>
    public IReadOnlyList<IrInterference> Interferences { get; }

    /// <summary>Appended to <c>package.json</c>'s <c>gaps</c>; each becomes unresolved coverage.</summary>
    public IReadOnlyList<Gap> Gaps { get; }
}
