using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Threading;
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
    /// Owner decision 159A, on review (004 research R19.9): this process's appends, one at a time, so no two of its
    /// threads meet in the file - the run's and the page's, SOLIDWORKS' and the tool-service gate's all write here.
    /// </summary>
    private static readonly object Gate = new object();

    /// <summary>
    /// Lines not yet in their file, by file, oldest first: kept when the file could not be written - something outside
    /// this process holding it past the waits below - and written ahead of the next line. Guarded by <see cref="Gate"/>.
    /// </summary>
    private static readonly Dictionary<string, Queue<string>> Unwritten =
        new Dictionary<string, Queue<string>>(StringComparer.OrdinalIgnoreCase);

    /// <summary>The most lines kept for one file that cannot be written; past it, the oldest go.</summary>
    private const int MostUnwritten = 1000;

    /// <summary>
    /// The waits, in milliseconds, before each try again while something outside this process holds the file - 300 in
    /// all - made only while no line waits already, so a file held for long costs each later line one try.
    /// </summary>
    private static readonly int[] HeldWaits = { 10, 20, 40, 80, 150 };

    private static readonly int[] NoWaits = new int[0];

    private static readonly Encoding Utf8 = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);

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
            Append(Path.Combine(folder, "addin.log"), line);
        }
        catch (Exception)
        {
            // There is nowhere left to report to.
        }
    }

    /// <summary>
    /// The append <see cref="Write"/> makes, on a file the caller names: one timestamped line (owner decision 159A, on
    /// review: the seam its tests write through, each to a file of its own, since <see cref="Folder"/> is the whole
    /// process's). Owner decision 159A, on review (the race review's finding R2): an append opened the file sharing it for
    /// reading only, under no lock, and a failure was the line's end, so two appends at once lost one. Now the appends of
    /// this process are made one at a time; a holder of the file is waited out briefly; and a line that still cannot be
    /// written is kept, with any before it, and written ahead of the next. Throws what is not the file being held - a path
    /// that cannot be a file, a disk that is full - the line kept all the same; <see cref="Write"/> swallows it.
    ///
    /// Owner decision 159A, on Codex's review of the merge (C2): the file is shared for reading only, so one writer at a
    /// time holds it, whatever process it is in. Shared for writing, two handles - this add-in's in two SOLIDWORKS
    /// sessions - each opened at the file's end as it then stood, and the later write went to the earlier end, over the
    /// other's line: the lock above reaches no other process. Writing alone, a writer of another process is a holder like
    /// any other: waited out, and a line not yet written kept. Simpler than a named lock across processes, and it asks
    /// nothing of the other writer but that it write as this one does.
    /// </summary>
    internal static void Append(string path, string line)
    {
        string text = string.Format("[{0:O}] {1}{2}", DateTimeOffset.Now, line, Environment.NewLine);
        lock (Gate)
        {
            if (!Unwritten.TryGetValue(path, out Queue<string>? waiting))
            {
                waiting = new Queue<string>();
                Unwritten.Add(path, waiting);
            }

            bool noneWaited = waiting.Count == 0;
            waiting.Enqueue(text);
            while (waiting.Count > MostUnwritten)
            {
                waiting.Dequeue();
            }

            if (TryAppend(path, string.Concat(waiting), noneWaited ? HeldWaits : NoWaits))
            {
                Unwritten.Remove(path);
            }
        }
    }

    /// <summary>
    /// Owner decision 159A, on the final review: writes the lines kept for every file something held, each tried as an
    /// append is - its holder waited out briefly - so a line kept is not lost with the process when the add-in unloads.
    /// A file still held keeps its lines. Never throws: there is nowhere left to report to.
    /// </summary>
    internal static void Flush()
    {
        lock (Gate)
        {
            foreach (string path in new List<string>(Unwritten.Keys))
            {
                try
                {
                    if (TryAppend(path, string.Concat(Unwritten[path]), HeldWaits))
                    {
                        Unwritten.Remove(path);
                    }
                }
                catch (Exception)
                {
                    // The lines stay kept; nothing else can be done with them.
                }
            }
        }
    }

    /// <summary>
    /// Appends <paramref name="text"/> to <paramref name="path"/>, writing alone - the file shared with readers only - and
    /// tries again after each of <paramref name="waits"/> while something holds it. Answers false when it is still held
    /// after the last.
    /// </summary>
    private static bool TryAppend(string path, string text, int[] waits)
    {
        byte[] bytes = Utf8.GetBytes(text);
        for (int attempt = 0; ; attempt++)
        {
            try
            {
                using (var stream = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.Read))
                {
                    stream.Write(bytes, 0, bytes.Length);
                }

                return true;
            }
            catch (IOException failure) when (IsHeld(failure))
            {
                if (attempt >= waits.Length)
                {
                    return false;
                }

                Thread.Sleep(waits[attempt]);
            }
        }
    }

    /// <summary>Whether <paramref name="failure"/> is the file held by another: a sharing or a lock violation.</summary>
    private static bool IsHeld(IOException failure)
    {
        const int SharingViolation = 32;
        const int LockViolation = 33;
        int code = failure.HResult & 0xFFFF;
        return code == SharingViolation || code == LockViolation;
    }
}
