using System;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Holds on the tool service's attachment as a fake gate hands them out (owner decision 152A, on the
/// Codex review: X2), counted: how many were taken, how many were let go, and what runs as each is
/// taken and let go. Letting one go twice counts once, as the gate's own holds do.
///
/// Shared by the suites that pin who holds the bridge and for how long - the Remodel host, the review
/// host and the pane's proxy - where the gate's own holds are pinned by
/// <see cref="ToolServiceWiringTests"/>.
/// </summary>
internal sealed class CountedHolds
{
    public int Taken { get; private set; }

    public int Released { get; private set; }

    /// <summary>Taken and not let go.</summary>
    public int Held => Taken - Released;

    /// <summary>Runs as each hold is taken, before it is handed over.</summary>
    public Action? OnTake { get; set; }

    /// <summary>Runs as each hold is let go, once.</summary>
    public Action? OnRelease { get; set; }

    public IDisposable? Take()
    {
        Taken++;
        OnTake?.Invoke();
        return new Hold(this);
    }

    private sealed class Hold : IDisposable
    {
        private CountedHolds? _holds;

        public Hold(CountedHolds holds)
        {
            _holds = holds;
        }

        public void Dispose()
        {
            CountedHolds? holds = _holds;
            _holds = null;
            if (holds != null)
            {
                holds.Released++;
                holds.OnRelease?.Invoke();
            }
        }
    }
}
