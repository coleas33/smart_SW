using System.IO;

namespace SwReview.AddIn;

/// <summary>
/// The Task Pane tab icon: the six PNGs SOLIDWORKS' <c>CreateTaskpaneView3</c> takes, one per
/// size, chosen by display scaling. They are drawn from <c>Icons\taskpane-source-512.png</c> by
/// <c>extractor/tools/make-taskpane-icons.py</c> and copied beside the add-in by
/// SwReview.AddIn.csproj, the same way the pages are.
///
/// All six or none: SOLIDWORKS is handed the whole set, and a set with a hole would be a tab
/// that draws at some scalings and not others. When any file is missing the caller falls back
/// to the stock icon, so a deploy that dropped the folder costs the icon and never the tab.
/// </summary>
internal static class TaskPaneIcons
{
    /// <summary>The sizes <c>CreateTaskpaneView3</c> wants, in the order it wants them.</summary>
    internal static readonly int[] Sizes = { 20, 32, 40, 64, 96, 128 };

    /// <summary>The subfolder beside the add-in that holds them.</summary>
    internal const string Folder = "Icons";

    internal static string FileName(int size) => "taskpane-" + size + ".png";

    /// <summary>
    /// The six paths under <paramref name="addInDirectory"/>, in <see cref="Sizes"/> order, or
    /// null when the directory is unnamed (<see cref="AssemblyRedirect.AddInDirectory"/> is
    /// empty when the add-in's folder cannot be named) or any one file is absent.
    /// </summary>
    internal static string[]? Resolve(string addInDirectory)
    {
        if (string.IsNullOrEmpty(addInDirectory))
        {
            return null;
        }

        var paths = new string[Sizes.Length];
        for (int i = 0; i < Sizes.Length; i++)
        {
            string path = Path.Combine(addInDirectory, Folder, FileName(Sizes[i]));
            if (!File.Exists(path))
            {
                return null;
            }

            paths[i] = path;
        }

        return paths;
    }
}
