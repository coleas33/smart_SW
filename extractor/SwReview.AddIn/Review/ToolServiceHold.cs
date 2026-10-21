using System;

namespace SwReview.AddIn.Review;

/// <summary>
/// Owner decision 152A, on the Codex review (X2): what work holds the tool service's attachment with
/// while it runs over the bridge - a remodel plan or run, a review session being made, a turn being
/// started through the pane - so that no follow of the active document takes the bridge down under
/// it. The add-in's hosts are handed <c>ToolServiceGate.HoldAttachment</c>, which answers a hold, or
/// null when no service is listening to hold; a hold is let go by disposing it.
/// </summary>
public static class ToolServiceHold
{
    /// <summary>
    /// What a host with no tool-service gate holds with: nothing, and letting it go does nothing. Every
    /// host's default, so a host built without a gate starts its work as it did before the holds.
    /// </summary>
    public static readonly IDisposable Nothing = new NothingHeld();

    private sealed class NothingHeld : IDisposable
    {
        public void Dispose()
        {
        }
    }
}
