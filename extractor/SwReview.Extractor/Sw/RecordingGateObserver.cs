using System;
using System.Collections.Generic;
using SwReview.Extractor.Guard;

namespace SwReview.Extractor.Sw;

/// <summary>
/// The distinct interop members a gate was asked about, in the order they were first seen,
/// and every refusal.
///
/// The <c>suppress-test</c> command writes this set to <c>suppress-test.log</c>, which is the
/// artifact SC-003 is audited against: "did the one mutating command touch anything but the
/// two exempted members?". A line per call is not an option - one run makes thousands of
/// gated calls on the SOLIDWORKS thread - and the distinct set is exactly what the audit
/// asks, at one hash lookup per call.
///
/// Not thread-safe, for the same reason <see cref="SwGate"/> is not: one gate, one observer,
/// one STA thread (constitution, Technical Constraints).
/// </summary>
public sealed class RecordingGateObserver : ISwGateObserver
{
    private readonly HashSet<string> _seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    private readonly List<string> _members = new List<string>();
    private readonly List<MutatingCallError> _refusals = new List<MutatingCallError>();

    /// <summary>Every member the gate was asked about, once each, in first-seen order.</summary>
    public IReadOnlyList<string> Members => _members;

    /// <summary>Every refusal the guard raised, in order.</summary>
    public IReadOnlyList<MutatingCallError> Refusals => _refusals;

    /// <inheritdoc />
    public void Gated(string interopMember)
    {
        if (string.IsNullOrWhiteSpace(interopMember))
        {
            return;
        }

        if (_seen.Add(interopMember))
        {
            _members.Add(interopMember);
        }
    }

    /// <inheritdoc />
    public void Refused(MutatingCallError refusal)
    {
        if (refusal != null)
        {
            _refusals.Add(refusal);
        }
    }
}
