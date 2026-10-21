using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
using SwReview.AddIn.Review;

namespace SwReview.AddIn.Native;

/// <summary>
/// The run root rule's answers from Windows (owner decision 154A, <see cref="RunRootRule"/>): what a drive
/// letter is, what a substituted one stands for, what each part of a path is, and a folder's final path.
///
/// <b>Nothing here goes over the network or through a link the rule has not already refused.</b> The drive's
/// kind (<c>GetDriveType</c>) and a substitution (<c>QueryDosDevice</c>) are read from the letter alone, before
/// any path on the drive is opened, so a mapped network drive is refused without a connection being made; a
/// part is opened as itself (<c>FILE_FLAG_OPEN_REPARSE_POINT</c>), so a link is named without being followed;
/// and a final path is read only of a local folder none of whose parts is a link.
///
/// <b>Every path is opened in its <c>\\?\</c> form</b>, which the rule can make because it hands this probe
/// full drive paths only: a run root longer than MAX_PATH is read past it, whatever path handling the process
/// runs with - and SOLIDWORKS, not the add-in, decides that.
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
    public RunRootDrive DriveOf(string driveRoot)
    {
        switch (GetDriveType(driveRoot))
        {
            case DriveRemote:
                return RunRootDrive.Network;
            case DriveNoRootDirectory:
                return RunRootDrive.Missing;
            default:
                return RunRootDrive.Local;
        }
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
                int error = Marshal.GetLastWin32Error();
                return error == ErrorFileNotFound || error == ErrorPathNotFound ? RunRootEntry.Missing : RunRootEntry.Other;
            }

            if (!GetFileInformationByHandleEx(
                    handle, FileAttributeTagInfoClass, out FileAttributeTagInfo info, (uint)Marshal.SizeOf(typeof(FileAttributeTagInfo))))
            {
                return RunRootEntry.Other;
            }

            if ((info.FileAttributes & FileAttributeReparsePoint) != 0 && (info.ReparseTag & ReparseTagNameSurrogate) != 0)
            {
                return RunRootEntry.Link;
            }

            return (info.FileAttributes & FileAttributeDirectory) != 0 ? RunRootEntry.Folder : RunRootEntry.Other;
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
}
