using System;

namespace SwReview.Extractor.Rms;

/// <summary>
/// The before, after and failed markers written around a native call in <c>remodel.open</c> and
/// <c>remodel.geometry</c> (U27, 2026-09-28). A native crash inside a COM call never returns, so
/// the request's completed line in <c>remodel.log</c> is never written; the last <c>before</c>
/// marker with no <c>after</c> names the call that was running when the process ended.
///
/// The <c>before</c> marker is handed to <paramref name="stage"/> <b>before</b> the call starts,
/// and the host's writer appends it to the file with one <c>File.AppendAllText</c>, so it is in
/// the operating system's hands before SOLIDWORKS is asked anything. A marker names a fixed
/// member and never a value, a path or a request field.
///
/// A marker that cannot be written is dropped: a diagnostic is never a reason to change the call
/// it describes.
/// </summary>
public static class RemodelStageMarkers
{
    /// <summary><paramref name="call"/>, with its markers.</summary>
    public static T Around<T>(Action<string>? stage, string name, Func<T> call)
    {
        if (call == null)
        {
            throw new ArgumentNullException(nameof(call));
        }

        Mark(stage, "before " + name);
        T answer;
        try
        {
            answer = call();
        }
        catch (Exception)
        {
            Mark(stage, "failed " + name);
            throw;
        }

        Mark(stage, "after " + name);
        return answer;
    }

    /// <inheritdoc cref="Around{T}(Action{string}, string, Func{T})" />
    public static void Around(Action<string>? stage, string name, Action call)
    {
        if (call == null)
        {
            throw new ArgumentNullException(nameof(call));
        }

        Around<object?>(stage, name, () =>
        {
            call();
            return null;
        });
    }

    private static void Mark(Action<string>? stage, string marker)
    {
        try
        {
            stage?.Invoke(marker);
        }
        catch (Exception)
        {
            // A diagnostic file is never a reason to alter the call it describes.
        }
    }
}
