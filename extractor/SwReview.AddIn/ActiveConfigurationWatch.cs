using System;
using SolidWorks.Interop.sldworks;

namespace SwReview.AddIn;

/// <summary>
/// A configuration switch inside the active document, told to the pane as a document change
/// (feature 009 FR-022, `specs/009-engineer-workspace/contracts/sessions.md` section 7).
///
/// The add-in listened to one SOLIDWORKS event, `ActiveDocChangeNotify`, so switching the open
/// assembly from Default to Machined told no tab anything: a review of Default stayed painted over
/// Machined, with Accept and Show live against a configuration it never saw. The Review page
/// already treats another configuration as another document (`web/shared/document.js`); what was
/// missing was the message. This follows the active document and holds at most one subscription
/// to its `ActiveConfigChangePostNotify` - the part's or the assembly's; a drawing has no
/// configuration of its own - and runs the add-in's document fan-out when it fires, so every host
/// posts `document.changed` with the new configuration.
///
/// <b>Behind a seam.</b> Subscribing and unsubscribing are delegates, so the rule - one
/// subscription, moved with the active document, dropped for a drawing or nothing, released on
/// dispose - is tested with fake documents (`ActiveConfigurationWatchTests`), and
/// <see cref="ForSolidWorks"/> holds the only interop: the two event handler types, which exist in
/// the SOLIDWORKS 2024 SP5 redist (research R2.18) and are confirmed firing at the next workstation
/// sitting (T081).
///
/// Threading: every call is on the SOLIDWORKS application thread - `ActiveDocChangeNotify` and
/// `ActiveConfigChangePostNotify` are raised there, and the add-in follows the first document from
/// `ConnectToSW` - so nothing here locks. Nothing leaves the event sink either: an exception out of
/// a COM sink is SOLIDWORKS' problem.
/// </summary>
public sealed class ActiveConfigurationWatch : IDisposable
{
    private readonly Func<object, Func<int>, bool> _subscribe;
    private readonly Action<object, Func<int>> _unsubscribe;
    private readonly Action _changed;

    /// <summary>
    /// The one delegate this watch ever subscribes, so every unsubscribe names the handler that
    /// was subscribed (a COM event is removed by an equal delegate).
    /// </summary>
    private readonly Func<int> _sink;

    private object? _followed;

    /// <param name="subscribe">Subscribes the sink to a document's configuration event and says
    /// whether the document has one (a part or an assembly does; a drawing does not).</param>
    /// <param name="unsubscribe">Removes the sink from a document it was subscribed to.</param>
    /// <param name="changed">What a configuration switch runs: the add-in's document fan-out.</param>
    public ActiveConfigurationWatch(
        Func<object, Func<int>, bool> subscribe,
        Action<object, Func<int>> unsubscribe,
        Action changed)
    {
        _subscribe = subscribe ?? throw new ArgumentNullException(nameof(subscribe));
        _unsubscribe = unsubscribe ?? throw new ArgumentNullException(nameof(unsubscribe));
        _changed = changed ?? throw new ArgumentNullException(nameof(changed));
        _sink = OnActiveConfigChangePostNotify;
    }

    /// <summary>
    /// The watch over a running SOLIDWORKS: a part's `DPartDocEvents` or an assembly's
    /// `DAssemblyDocEvents` `ActiveConfigChangePostNotify`, and nothing for any other document.
    /// </summary>
    public static ActiveConfigurationWatch ForSolidWorks(Action changed) =>
        new ActiveConfigurationWatch(
            (document, sink) =>
            {
                if (document is PartDoc part)
                {
                    part.ActiveConfigChangePostNotify += new DPartDocEvents_ActiveConfigChangePostNotifyEventHandler(sink);
                    return true;
                }

                if (document is AssemblyDoc assembly)
                {
                    assembly.ActiveConfigChangePostNotify += new DAssemblyDocEvents_ActiveConfigChangePostNotifyEventHandler(sink);
                    return true;
                }

                return false;
            },
            (document, sink) =>
            {
                if (document is PartDoc part)
                {
                    part.ActiveConfigChangePostNotify -= new DPartDocEvents_ActiveConfigChangePostNotifyEventHandler(sink);
                }
                else if (document is AssemblyDoc assembly)
                {
                    assembly.ActiveConfigChangePostNotify -= new DAssemblyDocEvents_ActiveConfigChangePostNotifyEventHandler(sink);
                }
            },
            changed);

    /// <summary>
    /// Follows <paramref name="activeDocument"/>: the previous document's subscription goes, and
    /// the new one's configuration event is subscribed when it has one. The same document again
    /// is left as it is - one subscription, however many times the active document is reported.
    /// </summary>
    public void Follow(object? activeDocument)
    {
        if (activeDocument != null && ReferenceEquals(activeDocument, _followed))
        {
            return;
        }

        Release();
        if (activeDocument != null && _subscribe(activeDocument, _sink))
        {
            _followed = activeDocument;
        }
    }

    public void Dispose() => Release();

    /// <summary>
    /// The event sink. Runs the fan-out and answers 0, whatever the fan-out does: nothing may
    /// leave a COM event sink.
    /// </summary>
    private int OnActiveConfigChangePostNotify()
    {
        try
        {
            _changed();
        }
        catch (Exception)
        {
            // The fan-out reports its own failures (SwReviewAddIn.Report); a throw here would
            // be SOLIDWORKS' to handle, in the middle of a configuration switch.
        }

        return 0;
    }

    /// <summary>Drops the current subscription, if any. A document already gone cannot refuse its release.</summary>
    private void Release()
    {
        object? followed = _followed;
        _followed = null;
        if (followed == null)
        {
            return;
        }

        try
        {
            _unsubscribe(followed, _sink);
        }
        catch (Exception)
        {
            // The document closed under the subscription; there is nothing left to release.
        }
    }
}
