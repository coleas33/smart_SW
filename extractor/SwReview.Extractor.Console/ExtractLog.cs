using System;
using System.Globalization;
using System.IO;
using System.Text;

namespace SwReview.Extractor.Console;

/// <summary>
/// <c>extract.log</c>, written next to the output directory (contracts/cli.md). The run is
/// unattended often enough that "it exited 1" is not a useful answer on its own; the log
/// carries the timestamps, the document, and the full exception.
/// </summary>
public sealed class ExtractLog : IDisposable
{
    public const string FileName = "extract.log";

    private readonly StringBuilder _lines = new StringBuilder();
    private readonly string? _path;

    /// <summary>Opens a log in <paramref name="directory"/>; a null directory logs to the console only.</summary>
    public ExtractLog(string? directory)
        : this(directory, FileName)
    {
    }

    /// <summary>
    /// The same log under another name. <c>suppress-test</c> writes
    /// <c>suppress-test.log</c> (contracts/cli.md): it is the SC-003 audit artifact for the
    /// one mutating command and must not be mixed into the dumps' <c>extract.log</c>.
    /// </summary>
    public ExtractLog(string? directory, string fileName)
    {
        if (string.IsNullOrWhiteSpace(fileName))
        {
            throw new ArgumentException("A log file name is required.", nameof(fileName));
        }

        if (!string.IsNullOrWhiteSpace(directory))
        {
            Directory.CreateDirectory(directory!);
            _path = System.IO.Path.Combine(directory!, fileName);
        }
    }

    /// <summary>Where the log will be written, or null when only the console gets it.</summary>
    public string? FilePath => _path;

    /// <summary>One timestamped line, to the log and to stderr.</summary>
    public void Write(string message)
    {
        string line = DateTimeOffset.Now.ToString("yyyy-MM-dd HH:mm:ss.fff K", CultureInfo.InvariantCulture)
            + "  " + message;

        _lines.AppendLine(line);
        System.Console.Error.WriteLine(line);
    }

    /// <summary>An exception with its type, message and stack.</summary>
    public void WriteError(string message, Exception error)
    {
        Write(message);
        _lines.AppendLine(error.ToString());
        System.Console.Error.WriteLine(error.Message);
    }

    /// <summary>Flushes to disk. Never throws: a failed log must not fail the dump.</summary>
    public void Dispose()
    {
        if (_path == null)
        {
            return;
        }

        try
        {
            File.AppendAllText(_path, _lines.ToString(), Encoding.UTF8);
        }
        catch (IOException ex)
        {
            System.Console.Error.WriteLine($"Could not write {_path}: {ex.Message}");
        }
        catch (UnauthorizedAccessException ex)
        {
            System.Console.Error.WriteLine($"Could not write {_path}: {ex.Message}");
        }
    }
}
