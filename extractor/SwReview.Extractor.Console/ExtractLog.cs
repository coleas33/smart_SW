using System;
using System.Globalization;
using System.IO;
using System.Text;

namespace SwReview.Extractor.Console;

/// <summary>
/// <c>extract.log</c>, written next to the output directory (contracts/cli.md). The run is
/// unattended often enough that "it exited 1" is not a useful answer on its own; the log
/// carries the timestamps, the document, and the full exception.
///
/// Each line is on disk as soon as it is logged (004 T331, owner decision 166A), the way
/// <c>ExtractionProgress</c> writes its markers: a run that hangs, is stopped with Ctrl+C or
/// crashes keeps every line it wrote before that.
/// </summary>
public sealed class ExtractLog : IDisposable
{
    public const string FileName = "extract.log";

    private readonly string? _path;
    private StreamWriter? _file;

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
            try
            {
                _file = new StreamWriter(
                    new FileStream(_path, FileMode.Append, FileAccess.Write, FileShare.ReadWrite),
                    Encoding.UTF8) { AutoFlush = true };
            }
            catch (IOException ex)
            {
                Unwritable(ex);
            }
            catch (UnauthorizedAccessException ex)
            {
                Unwritable(ex);
            }
        }
    }

    /// <summary>Where the log is written, or null when only the console gets it.</summary>
    public string? FilePath => _path;

    /// <summary>One timestamped line, to the log and to stderr.</summary>
    public void Write(string message)
    {
        string line = DateTimeOffset.Now.ToString("yyyy-MM-dd HH:mm:ss.fff K", CultureInfo.InvariantCulture)
            + "  " + message;

        ToFile(line);
        System.Console.Error.WriteLine(line);
    }

    /// <summary>An exception with its type, message and stack.</summary>
    public void WriteError(string message, Exception error)
    {
        Write(message);
        ToFile(error.ToString());
        System.Console.Error.WriteLine(error.Message);
    }

    /// <summary>Closes the file. Never throws: a failed log must not fail the dump.</summary>
    public void Dispose()
    {
        try
        {
            _file?.Dispose();
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }

        _file = null;
    }

    /// <summary>One line to the file, flushed. Never throws: after a failure the console alone gets the rest.</summary>
    private void ToFile(string text)
    {
        if (_file == null)
        {
            return;
        }

        try
        {
            _file.WriteLine(text);
        }
        catch (IOException ex)
        {
            Unwritable(ex);
        }
        catch (UnauthorizedAccessException ex)
        {
            Unwritable(ex);
        }
        catch (ObjectDisposedException ex)
        {
            Unwritable(ex);
        }
    }

    private void Unwritable(Exception ex)
    {
        System.Console.Error.WriteLine($"Could not write {_path}: {ex.Message}");
        Dispose();
    }
}
