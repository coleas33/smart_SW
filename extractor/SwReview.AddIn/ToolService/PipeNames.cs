using System;

namespace SwReview.AddIn.ToolService;

/// <summary>
/// The names the in-process tool service listens on.
///
/// One rule, and it is a lifetime rule rather than a naming preference (T050): every host gets
/// its own name. Two Task Panes in one SOLIDWORKS - two documents, or a pane rebuilt after the
/// add-in reloads - are two hosts in one process, and a fixed name would make the second one
/// fail to listen, or make the second host's page reach the first host's SOLIDWORKS scope.
/// A name is therefore derived from nothing the two hosts share.
///
/// The shape is `swreview-&lt;guid&gt;`, fixed by T047: no separator, no space, nothing that
/// has to be quoted, because the name travels to the backend in a JSON body and on to
/// `\\.\pipe\`.
/// </summary>
public static class PipeNames
{
    /// <summary>The prefix every tool-service pipe name carries.</summary>
    public const string ToolServicePrefix = "swreview-";

    /// <summary>A name no other host in this process, or any other, is using.</summary>
    public static string NewToolServiceName() =>
        ToolServicePrefix + Guid.NewGuid().ToString("N");
}
