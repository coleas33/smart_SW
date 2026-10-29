using System;
using System.Collections.Generic;

namespace SwReview.Extractor.Guard;

/// <summary>
/// What an allowlist guard answers a bare member name (owner decision 151A; contracts/guard.md section 9).
/// </summary>
public enum BareNamePolicy
{
    /// <summary>
    /// A bare name - the name every read call site gates its member under - is <see cref="ReadOnlyGuard"/>'s
    /// answer, unchanged: <see cref="DrawingOpenGuard"/>'s and <see cref="RemodelGuard"/>'s policy.
    /// </summary>
    ReadOnlyGuardsAnswer,

    /// <summary>
    /// Only the guard's own reads (<see cref="AllowlistGuard.Reads"/>), matched ordinally, pass; every other
    /// bare name is refused, naming it, whatever the read-only guard answers: <see cref="RemodelSeatGuard"/>'s
    /// policy, a closed allowlist since owner decision 148A.
    /// </summary>
    OwnReadsOnly,
}

/// <summary>
/// Owner decision 151A (feature 011, 2026-10-20; research R13, contracts/guard.md section 9): the rule the
/// product's three allowlist guards share - <see cref="DrawingOpenGuard"/>, <see cref="RemodelSeatGuard"/> and
/// <see cref="RemodelGuard"/> - held once, where each had written it in its own code (research R11.8 item 6).
///
/// The answers, in this order:
///   1. a missing name is an argument error, and any other is judged trimmed;
///   2. one of the guard's own interface-qualified keys (<see cref="Keys"/>), matched <b>ordinally</b> so a
///      mis-spelling fails closed rather than widening the surface, passes;
///   3. a name the guard refuses by name itself is refused, however it is spelled
///      (<see cref="RefuseByName"/>) - only <see cref="RemodelGuard"/> refuses any, its own fourth answer;
///   4. any other interface-qualified key is refused, naming it, because the keys are the whole of what the
///      guard's gate may do beyond reading; and
///   5. a bare name is answered by the guard's <see cref="BareNames"/> policy: the read-only guard's answer,
///      unchanged; or, for a closed allowlist, passed only if it is one of the guard's own <see cref="Reads"/>,
///      and refused, naming it, otherwise.
///
/// Each guard keeps its own list, its own words for a refusal (<see cref="Refusal"/>) and its own construction
/// site. This class adds no name to any list and widens no guard: its <see cref="Assert"/> cannot be
/// overridden, the one answer a guard may add, <see cref="RefuseByName"/>, can only refuse, and since the
/// decision's review a guard whose key is not interface-qualified, or whose read is not a bare member name,
/// fails as it is built. The tests read
/// each guard's keys and bare-name policy through it. <see cref="RemodelProbeGuard"/> and
/// <see cref="SuppressTestGuard"/> are not built on it: they are exemptions over the read-only guard, not
/// allowlists - a name on their lists passes, and every other, bare or qualified, is the read-only guard's
/// answer - so this rule would change their answers (research R13.1). The probe's lists are matched
/// ordinally since owner decision 160A and its review, a case variant of a run-scoped member refused before
/// the read-only guard is asked, and <see cref="SuppressTestGuard"/>'s ignoring case (research R14).
/// </summary>
public abstract class AllowlistGuard : ICallGuard
{
    private readonly HashSet<string> _keys;
    private readonly HashSet<string> _reads;

    /// <summary>An allowlist of <paramref name="keys"/>, whose bare names are <see cref="ReadOnlyGuard"/>'s answer.</summary>
    protected AllowlistGuard(IEnumerable<string> keys)
        : this(keys, BareNamePolicy.ReadOnlyGuardsAnswer, Array.Empty<string>())
    {
    }

    /// <summary>A closed allowlist: <paramref name="keys"/> and the guard's own <paramref name="reads"/>, and no other name.</summary>
    protected AllowlistGuard(IEnumerable<string> keys, IEnumerable<string> reads)
        : this(keys, BareNamePolicy.OwnReadsOnly, reads)
    {
    }

    private AllowlistGuard(IEnumerable<string> keys, BareNamePolicy bareNames, IEnumerable<string> reads)
    {
        _keys = new HashSet<string>(keys, StringComparer.Ordinal);
        _reads = new HashSet<string>(reads, StringComparer.Ordinal);

        // The rule's own invariant (decision 151A's review, finding N4), held as the guard is built rather than
        // by each guard's pinned list alone: every key is interface-qualified, so no bare name passes before the
        // read-only guard is asked, and every read is a bare member name - not blank, with no separator at all -
        // so a closed allowlist passes no qualified name as a read. A guard built otherwise is a programming
        // error, and fails as it is built, before it is asked anything.
        foreach (string key in _keys)
        {
            if (!CallKey.IsQualified(key))
            {
                throw new ArgumentException(
                    $"An allowlist guard's key is interface-qualified, such as \"IModelDoc2.Save3\"; got \"{key}\".",
                    nameof(keys));
            }
        }

        foreach (string read in _reads)
        {
            if (string.IsNullOrWhiteSpace(read) || read.IndexOf(CallKey.Separator) >= 0)
            {
                throw new ArgumentException(
                    $"An allowlist guard's read is a bare member name, such as \"GetTitle\"; got \"{read}\".",
                    nameof(reads));
            }
        }

        BareNames = bareNames;
        Keys = new ReadOnlySet<string>(_keys);
        Reads = new ReadOnlySet<string>(_reads);
    }

    /// <summary>
    /// The guard's own interface-qualified keys, for reading: a read-only view of the set <see cref="Assert"/>
    /// matches ordinally, which implements no mutable collection interface, so nothing done through it changes
    /// what the guard allows (owner decision 160A; a read-only copy until then).
    /// </summary>
    public IReadOnlyCollection<string> Keys { get; }

    /// <summary>What the guard answers a bare name.</summary>
    public BareNamePolicy BareNames { get; }

    /// <summary>
    /// The bare names a closed allowlist passes (<see cref="BareNamePolicy.OwnReadsOnly"/>), for reading, as
    /// <see cref="Keys"/> is; none for a guard whose bare names are the read-only guard's answer.
    /// </summary>
    public IReadOnlyCollection<string> Reads { get; }

    /// <inheritdoc />
    public void Assert(string interopMemberName)
    {
        if (string.IsNullOrWhiteSpace(interopMemberName))
        {
            throw new ArgumentException("An interop member name is required.", nameof(interopMemberName));
        }

        string key = interopMemberName.Trim();

        if (_keys.Contains(key))
        {
            return;
        }

        RefuseByName(key);

        if (CallKey.IsQualified(key))
        {
            throw new MutatingCallError(key, Refusal(key));
        }

        if (BareNames == BareNamePolicy.ReadOnlyGuardsAnswer)
        {
            // A bare member name is a read call site. The read-only rules apply to it unchanged.
            ReadOnlyGuard.Assert(key);
            return;
        }

        if (_reads.Contains(key))
        {
            return;
        }

        throw new MutatingCallError(key, Refusal(key));
    }

    /// <summary>The guard's own words for refusing <paramref name="key"/>, trimmed; they name it.</summary>
    protected abstract string Refusal(string key);

    /// <summary>
    /// The guard's own refusal by name, asked after its keys and before the rest of the rule: it throws
    /// <see cref="MutatingCallError"/> to refuse <paramref name="key"/>, trimmed, and returning lets the rule go
    /// on, so it can refuse and never allow. None by default; only <see cref="RemodelGuard"/> has one.
    /// </summary>
    protected virtual void RefuseByName(string key)
    {
    }
}
