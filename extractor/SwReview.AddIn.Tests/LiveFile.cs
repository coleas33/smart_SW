using System.Collections.Generic;
using System.IO;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Reads a file that another thread or process may still be writing, without getting in the
/// writer's way.
///
/// <c>File.ReadAllText</c> and <c>File.ReadAllLines</c> open for reading and share the file for
/// reading only. While they hold it, a writer's open fails - and the tool-service log's
/// <c>File.AppendAllText</c> swallows that failure, so the line is dropped - and they fail
/// themselves on a writer that already has it open. Opened here sharing read, write and delete,
/// a read never refuses a writer and is never refused by one. It can still see a last line
/// half-written, so a test that asserts on a line orders its read after the write it is
/// waiting for rather than relying on this.
/// </summary>
internal static class LiveFile
{
    public static string ReadAllText(string path)
    {
        using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
        using (var reader = new StreamReader(stream))
        {
            return reader.ReadToEnd();
        }
    }

    /// <summary>The lines as <c>File.ReadAllLines</c> splits them.</summary>
    public static string[] ReadAllLines(string path)
    {
        var lines = new List<string>();
        using (var reader = new StringReader(ReadAllText(path)))
        {
            string? line;
            while ((line = reader.ReadLine()) != null)
            {
                lines.Add(line);
            }
        }

        return lines.ToArray();
    }
}
