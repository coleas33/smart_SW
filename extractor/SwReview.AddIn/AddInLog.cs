using System;
using System.IO;
using SwReview.AddIn.Review;

namespace SwReview.AddIn;

/// <summary>
/// The add-in's one log file, <c>%LOCALAPPDATA%\SwReview\logs\addin.log</c>: the load
/// checkpoints, whatever <c>SwReviewAddIn.Report</c> records for a failure, and every
/// substitution <see cref="AssemblyRedirect"/> serves. One mechanism and one file, because an
/// add-in load failure is otherwise silent by construction and a second log would be a second
/// place to forget to look (docs/addin-load-fix.md).
///
/// A type of its own rather than a member of <see cref="SwReviewAddIn"/> for two reasons.
/// <see cref="AssemblyRedirect"/> writes here from inside an <c>AssemblyResolve</c> handler and
/// must not touch the add-in type to do it; and <see cref="Folder"/> could not otherwise be set
/// before the add-in's type initializer runs - assigning a static field on that class is itself
/// a trigger for it, and that initializer's own checkpoint is the line the seam exists to
/// redirect.
/// </summary>
internal static class AddInLog
{
    /// <summary>
    /// Where <c>addin.log</c> is written. Injected so that no test writes into the engineer's
    /// real log: that file is what docs/addin-load-fix.md tells them to read when the
    /// Tools &gt; Add-ins check box has reverted, and a timestamped line left there by
    /// <c>dotnet test</c> is indistinguishable from a real SOLIDWORKS activation.
    /// </summary>
    internal static Func<string> Folder = ReviewHostOptions.DefaultLogFolder;

    /// <summary>
    /// Appends one timestamped line. Never throws: every caller is on a path - COM activation,
    /// a failed bind, a load failure being reported - where there is nowhere left to report to.
    /// </summary>
    internal static void Write(string line)
    {
        try
        {
            string folder = Folder();
            Directory.CreateDirectory(folder);
            File.AppendAllText(
                Path.Combine(folder, "addin.log"),
                string.Format("[{0:O}] {1}{2}", DateTimeOffset.Now, line, Environment.NewLine));
        }
        catch (Exception)
        {
            // There is nowhere left to report to.
        }
    }
}
