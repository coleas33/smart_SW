using System.Collections.Generic;
using System.Linq;

namespace SwReview.Extractor.Tests;

/// <summary>
/// Owner decision 148A (feature 011 T186, research R12.3): the forms a path to a run's copy can take,
/// fictional, in one list that holds both seats to the one rule they take the copy by
/// (<c>RemodelCopy.CopyOf</c>) - the rule's own tests (<c>RemodelCopyTests</c>), the bridge's
/// <c>remodel.open</c> (<c>RemodelOpenHandlerTests</c>) and the add-in's pane seat
/// (<c>SwRemodelSeatTests</c>, which links this file into the add-in's suite).
///
/// <see cref="Accepted"/> holds the form a real run hands either seat - the run folder made in its full
/// form, its <c>copy/</c> and the part's name - and the spellings of a run's copy decision 144A's second
/// review took (T178): a share's path with either separator, a run folder directly under a share's root
/// or a mapped drive's, spaces, another letter case, spaces around the path and a <c>.</c> segment.
/// <see cref="Refused"/> holds everything else either seat may be handed: not the run's copy, not a full
/// path, a <c>..</c> segment, a device path, a copy folder in no run folder, and a path that names nothing.
/// </summary>
public static class RemodelCopyPathForms
{
    public const string Stamp = "20260927-100000-bracket-remodel";

    /// <summary>A run folder as <c>RunFolders</c> makes it, in its full form.</summary>
    public const string RunDirectory = @"C:\Fictional\runs\" + Stamp;

    /// <summary>The run's copy in it, as either seat is handed it by a real run.</summary>
    public const string CopyPath = RunDirectory + @"\copy\bracket-RMS.SLDPRT";

    private const string Share = @"\\server\share\runs\" + Stamp;
    private const string ShareRoot = @"\\server\share\" + Stamp;
    private const string MappedDrive = @"Z:\" + Stamp;
    private const string Spaces = @"C:\Users\Fictional Engineer\Documents\Remodel runs\20260927-100000-my bracket-remodel";

    /// <summary>The path as handed, its canonical form, and the run folder it is in.</summary>
    public static IEnumerable<object[]> Accepted() => new[]
    {
        Row(CopyPath, CopyPath, RunDirectory),
        Row(CopyPath.Replace('\\', '/'), CopyPath, RunDirectory),
        Row("  " + CopyPath + " ", CopyPath, RunDirectory),
        Row(RunDirectory + @"\.\copy\bracket-RMS.SLDPRT", CopyPath, RunDirectory),
        Row(RunDirectory + @"\COPY\bracket-RMS.sldprt", RunDirectory + @"\COPY\bracket-RMS.sldprt", RunDirectory),
        Row(Share + @"\copy\bracket-RMS.SLDPRT", Share + @"\copy\bracket-RMS.SLDPRT", Share),
        Row("//server/share/runs/" + Stamp + "/copy/bracket-RMS.SLDPRT", Share + @"\copy\bracket-RMS.SLDPRT", Share),
        Row(ShareRoot + @"\copy\bracket-RMS.SLDPRT", ShareRoot + @"\copy\bracket-RMS.SLDPRT", ShareRoot),
        Row(MappedDrive + @"\copy\bracket-RMS.SLDPRT", MappedDrive + @"\copy\bracket-RMS.SLDPRT", MappedDrive),
        Row(Spaces + @"\copy\my bracket-RMS.SLDPRT", Spaces + @"\copy\my bracket-RMS.SLDPRT", Spaces),
    };

    /// <summary>A path either seat refuses before SOLIDWORKS is asked anything.</summary>
    public static IEnumerable<object[]> Refused() => new[]
    {
        // Not the run's copy: the source, another kind of document in copy/, a part outside copy/, a folder.
        Row(@"C:\work\bracket.SLDPRT"),
        Row(RunDirectory + @"\copy\bracket-RMS.SLDASM"),
        Row(RunDirectory + @"\copy\bracket-RMS.SLDDRW"),
        Row(RunDirectory + @"\elsewhere\bracket-RMS.SLDPRT"),
        Row(RunDirectory + @"\bracket-RMS.SLDPRT"),
        Row(CopyPath + @"\"),

        // Not a full path - relative, relative to a drive's own folder or to the current drive's root - or none.
        Row(@"copy\bracket-RMS.SLDPRT"),
        Row(@"runs\" + Stamp + @"\copy\bracket-RMS.SLDPRT"),
        Row(@"C:copy\bracket-RMS.SLDPRT"),
        Row(@"C:runs\" + Stamp + @"\copy\bracket-RMS.SLDPRT"),
        Row(@"\Fictional\runs\" + Stamp + @"\copy\bracket-RMS.SLDPRT"),
        Row(string.Empty),
        Row("   "),

        // A '..' segment, refused on sight - one that canonicalizes onto the copy among them.
        Row(RunDirectory + @"\copy\..\copy\bracket-RMS.SLDPRT"),
        Row(@"C:\Fictional\work\..\runs\" + Stamp + @"\copy\bracket-RMS.SLDPRT"),
        Row("C:/Fictional/runs/" + Stamp + "/../" + Stamp + "/copy/bracket-RMS.SLDPRT"),

        // A device path, in each spelling.
        Row(@"\\?\" + CopyPath),
        Row(@"\\.\" + CopyPath),
        Row(@"\\?\UNC\server\share\runs\" + Stamp + @"\copy\bracket-RMS.SLDPRT"),
        Row("//?/" + CopyPath.Replace('\\', '/')),

        // A copy folder in no run folder: at the root of a drive or a share, or a share's own root.
        Row(@"C:\copy\bracket-RMS.SLDPRT"),
        Row(@"\\server\share\copy\bracket-RMS.SLDPRT"),
        Row(@"\\server\copy\bracket-RMS.SLDPRT"),

        // A path that names nothing: a character no path may hold, a colon after the drive's.
        Row(@"C:\Fictional\runs\bad<name>\copy\bracket-RMS.SLDPRT"),
        Row(CopyPath + ":stream"),
    };

    /// <summary><see cref="Refused"/> but the blank paths, which a request's own reader refuses before any rule.</summary>
    public static IEnumerable<object[]> RefusedThatARequestCanCarry() =>
        Refused().Where(row => !string.IsNullOrWhiteSpace((string)row[0]));

    private static object[] Row(params object[] values) => values;
}
