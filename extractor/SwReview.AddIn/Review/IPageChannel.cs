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
/// </summary>
public interface IPageChannel
{
    /// <summary>Sends one `{type, id, payload}` document to the page.</summary>
    void PostMessage(string json);
}
