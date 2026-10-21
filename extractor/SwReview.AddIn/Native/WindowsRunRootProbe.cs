using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
using SwReview.AddIn.Review;

namespace SwReview.AddIn.Native;

/// <summary>
/// The run root rule's answers from Windows (owner decision 154A, <see cref="RunRootRule"/>): a root's full
/// path, what a drive letter is, what a substituted one stands for, what each part of a path is, a folder's
/// final path and its long-name form.
///
/// <b>Nothing here goes over the network or through a link the rule has not already refused.</b> A full path is
/// made from the text alone (<c>GetFullPathNameW</c>), reading nothing - not <c>Path.GetFullPath</c>, which
/// expands an 8.3 short name by reading each folder of the path (the reviews of decision 154A, finding F1). The
/// drive's kind (<c>GetDriveType</c>) and a substitution (<c>QueryDosDevice</c>) are read from the letter
/// alone, before any path on the drive is opened, so a mapped network drive is refused without a connection
/// being made; a part is opened as itself (<c>FILE_FLAG_OPEN_REPARSE_POINT</c>), so a link is named without
/// being followed; and a final path and a long-name form are read only of a local folder none of whose parts is
/// a link.
///
/// <b>Every path is opened in its <c>\\?\</c> form</b>, which the rule can make because it hands this probe
/// full drive paths only, and <c>GetFullPathNameW</c> makes a full path of any length: the rule judges a run
/// root longer than MAX_PATH whatever path handling the process runs with - and SOLIDWORKS, not the add-in,
/// decides that. Its run folders are another matter: they are made through <c>Path.GetFullPath</c>, which
/// under the legacy path handling SOLIDWORKS most likely runs the add-in with refuses such a root before any
/// folder is made, and the run says so (<c>RunFolderFailed</c>; the reviews' N9).
///
/// A link is a name-surrogate reparse point: a junction, a symbolic link, or a volume's mount point, which
/// shares the junction's tag. A cloud file's reparse point - a OneDrive folder - is not one: it names no other
/// path, and the folder's final path is its own.
/// </summary>
public sealed class WindowsRunRootProbe : IRunRootProbe
{
    /// <summary>The one probe the add-in reads Windows through; it holds nothing.</summary>
    public static readonly WindowsRunRootProbe Instance = new WindowsRunRootProbe();

    private const uint DriveNoRootDirectory = 1;
    private const uint DriveRemote = 4;

    private const uint FileReadAttributes = 0x80;
    private const uint FileShareAll = 0x1 | 0x2 | 0x4;
    private const uint OpenExisting = 3;
    private const uint FileFlagBackupSemantics = 0x02000000;
    private const uint FileFlagOpenReparsePoint = 0x00200000;

    private const uint FileAttributeDirectory = 0x10;
    private const uint FileAttributeReparsePoint = 0x400;
    private const uint ReparseTagNameSurrogate = 0x20000000;

    /// <summary><c>FILE_INFO_BY_HANDLE_CLASS.FileAttributeTagInfo</c>.</summary>
    private const int FileAttributeTagInfoClass = 9;

    /// <summary><c>FILE_NAME_NORMALIZED | VOLUME_NAME_DOS</c>: the long names, under a drive letter or a share.</summary>
    private const uint FinalNameNormalizedDos = 0;

    private const int ErrorFileNotFound = 2;
    private const int ErrorPathNotFound = 3;

    /// <summary>The longest path Windows names, and so the longest answer either call can give.</summary>
    private const int LongestPath = 32767;

    private WindowsRunRootProbe()
    {
    }

    /// <inheritdoc/>
    public RunRootDrive DriveOf(string driveRoot) => DriveKindOf(GetDriveType(driveRoot));

    /// <summary>
    /// What kind of drive a <c>GetDriveType</c> answer names (the reviews of decision 154A, finding F4): a remote
    /// drive is a mapped network drive, a root that is not there is no drive, and every other answer - a fixed,
    /// removable, optical or RAM disk, or one Windows cannot tell - is a local drive, whose parts the rule reads
    /// one by one. Apart from <see cref="DriveOf"/> so that this table, which alone refuses the most common share
    /// - a mapped home drive, which no test can make - is pinned answer by answer.
    /// </summary>
    internal static RunRootDrive DriveKindOf(uint driveType)
    {
        switch (driveType)
        {
            case DriveRemote:
                return RunRootDrive.Network;
            case DriveNoRootDirectory:
                return RunRootDrive.Missing;
            default:
                return RunRootDrive.Local;
        }
    }

    /// <summary>
    /// What a part is, from what its open answered and, when it opened, its attributes and reparse tag (the
    /// reviews of decision 154A, findings F2 and F4): not there - file or path not found - is missing; an open
    /// that failed for any other reason, its attributes denied or a drive not ready among them, or attributes
    /// that could not be read, leave it unreadable, what it is untold; a name-surrogate reparse point - a
    /// junction, a symbolic link, a mount point - is a link, and a cloud file's, which names no other path, is
    /// not; a folder is a folder; anything else there is not one. Apart from <see cref="EntryOf"/> so that each
    /// answer is pinned, where a test cannot make every one of them happen.
    /// </summary>
    /// <param name="openError">The open's error, or 0 when it opened.</param>
    /// <param name="attributes">The part's attributes and reparse tag, or null when they could not be read.</param>
    internal static RunRootEntry EntryKindOf(int openError, (uint Attributes, uint ReparseTag)? attributes)
    {
        if (openError != 0)
        {
            return openError == ErrorFileNotFound || openError == ErrorPathNotFound ? RunRootEntry.Missing : RunRootEntry.Unreadable;
        }

        if (attributes == null)
        {
            return RunRootEntry.Unreadable;
        }

        (uint attributeBits, uint reparseTag) = attributes.Value;
        if ((attributeBits & FileAttributeReparsePoint) != 0 && (reparseTag & ReparseTagNameSurrogate) != 0)
        {
            return RunRootEntry.Link;
        }

        return (attributeBits & FileAttributeDirectory) != 0 ? RunRootEntry.Folder : RunRootEntry.Other;
    }

    /// <inheritdoc/>
    public string? FullPathOf(string root) => LexicalFullPathOf(root);

    /// <summary>
    /// A root's full path made from its text alone, as <c>GetFullPathNameW</c> makes it - against the current
    /// folder for a relative root - with nothing on the disk or the network read; null when it has none.
    /// </summary>
    internal static string? LexicalFullPathOf(string root)
    {
        var buffer = new char[LongestPath + 1];
        uint length = GetFullPathName(root, (uint)buffer.Length, buffer, IntPtr.Zero);
        return length == 0 || length >= buffer.Length ? null : new string(buffer, 0, (int)length);
    }

    /// <inheritdoc/>
    public string? LongPathOf(string folder)
    {
        var buffer = new char[LongestPath + 1];
        uint length = GetLongPathName(@"\\?\" + folder, buffer, (uint)buffer.Length);
        return length == 0 || length >= buffer.Length ? null : WithoutDevicePrefix(new string(buffer, 0, (int)length));
    }

    /// <inheritdoc/>
    public string? SubstituteOf(string drive)
    {
        var answer = new char[LongestPath + 1];
        uint length = QueryDosDevice(drive, answer, (uint)answer.Length);
        return length == 0 ? null : SubstitutedFolder(new string(answer, 0, (int)length));
    }

    /// <summary>
    /// The folder a <c>QueryDosDevice</c> answer names for a drive substituted by <c>subst</c>, or null: the
    /// answer is a list, the mapping in force first and each item ending in a NUL, and a substitution is
    /// <c>\??\</c> and the folder - <c>\??\UNC\server\share</c> for a share's. A volume
    /// (<c>\Device\HarddiskVolume4</c>) or a mapped network drive (<c>\Device\LanmanRedirector\...</c>) is a
    /// device, not a folder.
    /// </summary>
    internal static string? SubstitutedFolder(string answer)
    {
        string current = answer.Split('\0')[0];
        if (!current.StartsWith(@"\??\", StringComparison.Ordinal))
        {
            return null;
        }

        string folder = current.Substring(4);
        return folder.StartsWith(@"UNC\", StringComparison.OrdinalIgnoreCase) ? @"\\" + folder.Substring(4) : folder;
    }

    /// <inheritdoc/>
    public RunRootEntry EntryOf(string path)
    {
        using (SafeFileHandle handle = Open(path, FileFlagBackupSemantics | FileFlagOpenReparsePoint))
        {
            if (handle.IsInvalid)
            {
                return EntryKindOf(Marshal.GetLastWin32Error(), null);
            }

            return GetFileInformationByHandleEx(
                    handle, FileAttributeTagInfoClass, out FileAttributeTagInfo info, (uint)Marshal.SizeOf(typeof(FileAttributeTagInfo)))
                ? EntryKindOf(0, (info.FileAttributes, info.ReparseTag))
                : EntryKindOf(0, null);
        }
    }

    /// <inheritdoc/>
    public string? FinalPathOf(string folder)
    {
        using (SafeFileHandle handle = Open(folder, FileFlagBackupSemantics))
        {
            if (handle.IsInvalid)
            {
                return null;
            }

            var buffer = new char[LongestPath + 1];
            uint length = GetFinalPathNameByHandle(handle, buffer, (uint)buffer.Length, FinalNameNormalizedDos);
            return length == 0 || length >= buffer.Length ? null : WithoutDevicePrefix(new string(buffer, 0, (int)length));
        }
    }

    /// <summary>A final path as a path: <c>\\?\C:\...</c> as <c>C:\...</c>, and <c>\\?\UNC\server\share</c> as <c>\\server\share</c>.</summary>
    private static string WithoutDevicePrefix(string final)
    {
        if (final.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase))
        {
            return @"\\" + final.Substring(8);
        }

        return final.StartsWith(@"\\?\", StringComparison.Ordinal) ? final.Substring(4) : final;
    }

    /// <summary>The part itself, for its attributes only, shared with every other reader and writer.</summary>
    private static SafeFileHandle Open(string path, uint flags) =>
        CreateFile(@"\\?\" + path, FileReadAttributes, FileShareAll, IntPtr.Zero, OpenExisting, flags, IntPtr.Zero);

    [StructLayout(LayoutKind.Sequential)]
    private struct FileAttributeTagInfo
    {
        public uint FileAttributes;
        public uint ReparseTag;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, EntryPoint = "GetDriveTypeW")]
    private static extern uint GetDriveType(string rootPathName);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, EntryPoint = "QueryDosDeviceW", SetLastError = true)]
    private static extern uint QueryDosDevice(string deviceName, [Out] char[] targetPath, uint max);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, EntryPoint = "CreateFileW", SetLastError = true)]
    private static extern SafeFileHandle CreateFile(
        string fileName, uint desiredAccess, uint shareMode, IntPtr securityAttributes,
        uint creationDisposition, uint flagsAndAttributes, IntPtr templateFile);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandleEx(
        SafeFileHandle file, int informationClass, out FileAttributeTagInfo information, uint bufferSize);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, EntryPoint = "GetFinalPathNameByHandleW", SetLastError = true)]
    private static extern uint GetFinalPathNameByHandle(SafeFileHandle file, [Out] char[] filePath, uint size, uint flags);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, EntryPoint = "GetFullPathNameW", SetLastError = true)]
    private static extern uint GetFullPathName(string fileName, uint bufferLength, [Out] char[] buffer, IntPtr filePart);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, EntryPoint = "GetLongPathNameW", SetLastError = true)]
    private static extern uint GetLongPathName(string shortPath, [Out] char[] longPath, uint size);
}
