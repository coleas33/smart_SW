using System;
using System.Collections.Generic;
using SwReview.Extractor.Interference;

namespace SwReview.Extractor.Tests.Fakes;

/// <summary>
/// Records what <see cref="InterferenceRunSettings.ApplyTo"/> wrote, under the property
/// names SOLIDWORKS uses. The point of T065: the flag-to-API mapping is asserted without a
/// seat, so a renamed or swapped property fails here rather than on the workstation.
/// </summary>
public sealed class RecordingManagerProperties : IInterferenceManagerProperties
{
    public bool? TreatCoincidenceAsInterferenceValue { get; private set; }

    public bool? TreatSubAssembliesAsComponentsValue { get; private set; }

    public bool? IncludeMultibodyPartInterferencesValue { get; private set; }

    public bool? IgnoreHiddenBodiesValue { get; private set; }

    public bool? CreateFastenersFolderValue { get; private set; }

    public bool TreatCoincidenceAsInterference
    {
        set { TreatCoincidenceAsInterferenceValue = value; }
    }

    public bool TreatSubAssembliesAsComponents
    {
        set { TreatSubAssembliesAsComponentsValue = value; }
    }

    public bool IncludeMultibodyPartInterferences
    {
        set { IncludeMultibodyPartInterferencesValue = value; }
    }

    public bool IgnoreHiddenBodies
    {
        set { IgnoreHiddenBodiesValue = value; }
    }

    public bool CreateFastenersFolder
    {
        set { CreateFastenersFolderValue = value; }
    }
}

/// <summary>A component handle a fake result can hand back; stands in for an IComponent2.</summary>
public sealed class FakeComponent
{
    public FakeComponent(string id, string? patternId = null)
    {
        Id = id;
        PatternId = patternId;
    }

    public string Id { get; }

    public string? PatternId { get; }

    /// <summary>The pair member a test hands to the runner.</summary>
    public InterferenceComponent AsPairMember() => new InterferenceComponent(Id, PatternId, this);

    public override string ToString() => Id;
}

/// <summary>One row a fake detector hands back.</summary>
public sealed class FakeInterferenceResult : IInterferenceResult
{
    private readonly List<object> _components = new List<object>();

    public FakeInterferenceResult(double volume, params FakeComponent[] components)
    {
        Volume = volume;
        _components.AddRange(components);
    }

    public double Volume { get; }

    public IReadOnlyList<object> Components
    {
        get
        {
            if (ThrowOnComponents != null)
            {
                throw ThrowOnComponents;
            }

            return _components;
        }
    }

    public bool IsFastener { get; set; }

    public bool IsPossibleInterference { get; set; }

    /// <summary>Set to make reading the components fail, the way a stale RCW would.</summary>
    public Exception? ThrowOnComponents { get; set; }
}

/// <summary>
/// A detector with no SOLIDWORKS behind it. <see cref="Answer"/> decides what each scope
/// returns, so a test can make one pair succeed and the next throw.
/// </summary>
public sealed class FakeInterferenceDetector : IInterferenceDetector
{
    private readonly Func<IReadOnlyList<object>, IReadOnlyList<IInterferenceResult>> _answer;

    public FakeInterferenceDetector(
        Func<IReadOnlyList<object>, IReadOnlyList<IInterferenceResult>>? answer = null)
    {
        _answer = answer ?? (scope => new IInterferenceResult[0]);
    }

    /// <summary>What <see cref="Configure"/> was given, mapped onto the manager's names.</summary>
    public RecordingManagerProperties Properties { get; } = new RecordingManagerProperties();

    public InterferenceRunSettings? ConfiguredWith { get; private set; }

    /// <summary>Every scope the runner asked for, in order.</summary>
    public List<IReadOnlyList<object>> Scopes { get; } = new List<IReadOnlyList<object>>();

    public int DoneCount { get; private set; }

    public Exception? ThrowOnConfigure { get; set; }

    public Exception? ThrowOnDone { get; set; }

    public void Configure(InterferenceRunSettings settings)
    {
        if (ThrowOnConfigure != null)
        {
            throw ThrowOnConfigure;
        }

        ConfiguredWith = settings;
        settings.ApplyTo(Properties);
    }

    public void Scope(IReadOnlyList<object> componentHandles)
    {
        Scopes.Add(componentHandles);
    }

    public int GetInterferenceCount() => _answer(CurrentScope).Count;

    public IReadOnlyList<IInterferenceResult> GetInterferences() => _answer(CurrentScope);

    public void Done()
    {
        DoneCount++;
        if (ThrowOnDone != null)
        {
            throw ThrowOnDone;
        }
    }

    private IReadOnlyList<object> CurrentScope =>
        Scopes.Count == 0 ? new object[0] : Scopes[Scopes.Count - 1];
}

/// <summary>Hands out one <see cref="FakeInterferenceDetector"/>, or fails to.</summary>
public sealed class FakeInterferenceSource : IInterferenceSource
{
    private readonly FakeInterferenceDetector? _detector;
    private readonly Exception? _openFailure;

    public FakeInterferenceSource(FakeInterferenceDetector detector)
    {
        _detector = detector;
    }

    public FakeInterferenceSource(Exception openFailure)
    {
        _openFailure = openFailure;
    }

    public int OpenCount { get; private set; }

    public IInterferenceDetector Open()
    {
        OpenCount++;
        if (_openFailure != null)
        {
            throw _openFailure;
        }

        return _detector!;
    }
}
