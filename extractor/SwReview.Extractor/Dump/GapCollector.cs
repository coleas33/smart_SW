using System;
using System.Collections.Generic;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Dump;

/// <summary>
/// The dump's record of everything it could not read (T048). Every gap becomes an
/// unresolved coverage item in the review, so a feature the extractor skipped is visible
/// to the engineer instead of silently absent (constitution Principle I).
///
/// Two exception types deliberately are NOT caught:
///   <see cref="CircuitOpenError"/> - SOLIDWORKS has stopped answering, so one gap per
///     remaining entity would bury the real cause. The caller aborts the phase.
///   <see cref="MutatingCallError"/> - the read-only guard refused a call we should never
///     have made. That is our bug, not a property of the model.
/// </summary>
public sealed class GapCollector
{
    private readonly List<Gap> _gaps = new List<Gap>();

    /// <summary>A snapshot in the order the gaps were recorded.</summary>
    public IReadOnlyList<Gap> Gaps => _gaps.ToArray();

    /// <summary>
    /// The <c>GetTypeName2</c> names the dump saw and did not read. It lives here because
    /// this collector is the one object all three feature read sites already hold, and
    /// because an unread feature type is the same kind of unresolved coverage as a gap.
    /// PackageWriter turns it into gaps once the traversal is over.
    /// </summary>
    public TypeNameCensus TypeNames { get; } = new TypeNameCensus();

    /// <summary>How many gaps have been recorded so far.</summary>
    public int Count => _gaps.Count;

    /// <summary>Records a gap the caller has already classified.</summary>
    public void Add(GapKind kind, string entityKind, string? entityId, string reason, string? error)
    {
        if (string.IsNullOrWhiteSpace(entityKind))
        {
            throw new ArgumentException("A gap needs the kind of entity it is about.", nameof(entityKind));
        }

        if (string.IsNullOrWhiteSpace(reason))
        {
            throw new ArgumentException("A gap needs a reason an engineer can read.", nameof(reason));
        }

        _gaps.Add(new Gap
        {
            Kind = kind,
            EntityKind = entityKind,
            EntityId = entityId,
            Reason = reason,
            Error = error,
        });
    }

    /// <summary>Merges gaps recorded elsewhere, keeping their order.</summary>
    public void AddRange(IEnumerable<Gap> gaps)
    {
        if (gaps == null)
        {
            throw new ArgumentNullException(nameof(gaps));
        }

        _gaps.AddRange(gaps);
    }

    /// <summary>Turns an exception into a <see cref="GapKind.ToolError"/> gap.</summary>
    public void Record(string entityKind, string? entityId, string reason, Exception error)
    {
        if (error == null)
        {
            throw new ArgumentNullException(nameof(error));
        }

        Add(GapKind.ToolError, entityKind, entityId, reason, Describe(error));
    }

    /// <summary>
    /// Runs one extraction step. Returns false and records a gap if it threw, so the
    /// traversal continues to the next entity.
    /// </summary>
    public bool TryStep(string entityKind, string? entityId, string reason, Action step)
    {
        if (step == null)
        {
            throw new ArgumentNullException(nameof(step));
        }

        try
        {
            step();
            return true;
        }
        catch (CircuitOpenError)
        {
            throw;
        }
        catch (MutatingCallError)
        {
            throw;
        }
        catch (Exception ex)
        {
            Record(entityKind, entityId, reason, ex);
            return false;
        }
    }

    /// <summary>
    /// Runs one extraction step that produces a value. Returns null and records a gap if
    /// it threw. A step that legitimately has no value returns null without a gap; use
    /// <see cref="Add"/> for that case so the reason is recorded.
    /// </summary>
    public T? TryStep<T>(string entityKind, string? entityId, string reason, Func<T?> step)
        where T : class
    {
        if (step == null)
        {
            throw new ArgumentNullException(nameof(step));
        }

        try
        {
            return step();
        }
        catch (CircuitOpenError)
        {
            throw;
        }
        catch (MutatingCallError)
        {
            throw;
        }
        catch (Exception ex)
        {
            Record(entityKind, entityId, reason, ex);
            return null;
        }
    }

    /// <summary>
    /// The exception type and message. The type matters: an InvalidCastException from
    /// interop reads very differently from a COMException with an HRESULT.
    /// </summary>
    private static string Describe(Exception error) =>
        $"{error.GetType().Name}: {error.Message}";
}
