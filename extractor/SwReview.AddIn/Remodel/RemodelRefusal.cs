using System;

namespace SwReview.AddIn.Remodel;

/// <summary>
/// A refusal the pipeline was given, on its way to the page as
/// `error {error_class, message}` (`contracts/pane-remodel-messages.md`, "Refusal classes").
///
/// It exists so that a named refusal survives the trip through
/// <see cref="IRemodelPipeline"/>. The pipeline's members return readings, not error objects -
/// `OpenCopy` hands back a <see cref="RemodelCopyReading"/> and has nowhere to put "the source
/// has unsaved changes" - so the refusal travels as an exception with its class attached
/// instead of as prose inside a generic failure. A host that caught only
/// <see cref="Exception"/> would answer every one of them `HostError`, and the page would show
/// the same sentence for a weldment, a dirty source and a dead bridge.
///
/// <see cref="ErrorClass"/> is one of the contract's classes, and the message is the sentence
/// the engineer reads. Both come from whoever refused - the backend's `{error_class, message}`
/// body, or this pipeline when it refuses before it calls (no document, no bridge, no
/// backend).
/// </summary>
public sealed class RemodelRefusal : Exception
{
    public RemodelRefusal(
        string errorClass, string message, bool retryable = false, Exception? inner = null)
        : base(message, inner)
    {
        ErrorClass = errorClass ?? throw new ArgumentNullException(nameof(errorClass));
        Retryable = retryable;
    }

    /// <summary>One of `contracts/pane-remodel-messages.md`'s refusal classes.</summary>
    public string ErrorClass { get; }

    /// <summary>Whether pressing the button again could succeed; the page says so.</summary>
    public bool Retryable { get; }
}
