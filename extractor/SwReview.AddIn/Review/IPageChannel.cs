namespace SwReview.AddIn.Review;

/// <summary>
/// The one thing <see cref="ReviewHost"/> needs from WebView2: a way to send a JSON message to
/// the page.
///
/// It exists so the host's whole message contract can be tested without a WebView2 instance -
/// there is no WebView2 in a unit-test process, and there is no SOLIDWORKS either. The real
/// implementation (T043) wraps `CoreWebView2.PostWebMessageAsJson`.
///
/// Two obligations the implementation carries, both of them WebView2's rules rather than ours:
/// `PostWebMessageAsJson` has UI-thread affinity, so an implementation called from a
/// background thread marshals onto the pane control; and messages from the page are delivered
/// to <see cref="ReviewHost.Receive"/> one at a time, in arrival order, because the host's
/// handlers are not re-entrant.
///
/// And one that is ours (owner decision 155A's review): that marshalling queues the post and
/// returns; it never waits on the pane's thread, which in SOLIDWORKS is the application thread.
/// A host may post under a lock the application thread takes - <c>RemodelHost</c> posts `init`
/// under the lock that orders a run's ending, which the application thread takes when a
/// session's ending is told during a run - and a post that waited on that thread could hang
/// SOLIDWORKS.
/// </summary>
public interface IPageChannel
{
    /// <summary>
    /// Sends one `{type, id, payload}` document to the page: queued onto the pane's thread when
    /// called from another, and never waiting on it.
    /// </summary>
    void PostMessage(string json);
}
