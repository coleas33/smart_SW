using System;
using System.Collections.Generic;
using System.Linq;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Tests.Fakes;

/// <summary>One call the seam made, with its arguments, rendered for an ordered comparison.</summary>
internal sealed class FakeOpenCall
{
    public FakeOpenCall(string name, params object?[] arguments)
    {
        Name = name;
        Arguments = arguments;
    }

    public string Name { get; }

    public object?[] Arguments { get; }

    public override string ToString() =>
        Name + " " + string.Join(" ", Arguments.Select(argument => Convert.ToString(argument, System.Globalization.CultureInfo.InvariantCulture)));
}

/// <summary>
/// SOLIDWORKS as the seam sees it: which documents are open, and what the open does. The open
/// document answers <see cref="Opened"/> until the seam closes it.
/// </summary>
internal sealed class FakeDrawingOpenHost : IDrawingOpenHost
{
    private readonly Dictionary<string, object> _open = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);

    public List<FakeOpenCall> Calls { get; } = new List<FakeOpenCall>();

    public object Opened { get; } = new object();

    public Exception? OpenFailure { get; set; }

    public bool OpenAnswersNull { get; set; }

    public int OpenErrors { get; set; }

    public int OpenWarnings { get; set; }

    /// <summary>What the lookup answers once the seam opened the drawing, instead of <see cref="Opened"/>.</summary>
    public object? AfterOpenAnswer { get; set; }

    public bool AfterOpenAnswersNothing { get; set; }

    /// <summary>Thrown by <c>DocumentVisible(true, ...)</c>, the restore, when set.</summary>
    public Exception? RestoreFailure { get; set; }

    /// <summary>Thrown by the lookup once the seam opened the drawing (the close's identity check), when set.</summary>
    public Exception? AfterOpenLookupFailure { get; set; }

    /// <summary>Thrown by <c>CloseDoc</c>, when set.</summary>
    public Exception? CloseFailure { get; set; }

    /// <summary>
    /// What <c>IsOpenedReadOnly</c> answers (decision 136A): true, as SOLIDWORKS should answer for
    /// a document <c>OpenDoc6</c> opened with the read-only option, unless a test says otherwise.
    /// </summary>
    public bool OpenedReadOnly { get; set; } = true;

    /// <summary>Thrown by <c>IsOpenedReadOnly</c>, when set.</summary>
    public Exception? ReadOnlyFailure { get; set; }

    /// <summary>
    /// Run after each lookup has answered, with the path it was asked (decision 141A's tests): what
    /// the engineer does in SOLIDWORKS between one lookup and the next, such as
    /// <see cref="EngineerCloses"/>.
    /// </summary>
    public Action<string>? AfterLookup { get; set; }

    public object AlreadyOpen(string path)
    {
        var document = new object();
        _open[path] = document;
        return document;
    }

    /// <summary>The engineer closes the drawing in SOLIDWORKS: no call of the seam's, so none is recorded.</summary>
    public void EngineerCloses(string path) => _open.Remove(path);

    public object? OpenDocument(string path)
    {
        Calls.Add(new FakeOpenCall("OpenDocument", path));
        try
        {
            return Lookup(path);
        }
        finally
        {
            AfterLookup?.Invoke(path);
        }
    }

    private object? Lookup(string path)
    {
        if (!_open.TryGetValue(path, out object? document))
        {
            return null;
        }

        if (ReferenceEquals(document, Opened))
        {
            if (AfterOpenLookupFailure != null)
            {
                throw AfterOpenLookupFailure;
            }

            return AfterOpenAnswersNothing ? null : AfterOpenAnswer ?? document;
        }

        return document;
    }

    public void DocumentVisible(bool visible, int documentType)
    {
        Calls.Add(new FakeOpenCall("DocumentVisible", visible, documentType));
        if (visible && RestoreFailure != null)
        {
            throw RestoreFailure;
        }
    }

    public object? OpenDoc6(string path, int documentType, int options, string configuration, out int errors, out int warnings)
    {
        Calls.Add(new FakeOpenCall("OpenDoc6", path, documentType, options, configuration));
        errors = OpenErrors;
        warnings = OpenWarnings;
        if (OpenFailure != null)
        {
            throw OpenFailure;
        }

        if (OpenAnswersNull)
        {
            return null;
        }

        _open[path] = Opened;
        return Opened;
    }

    /// <summary>Recorded with which document it was asked of: the one the open returned, or another.</summary>
    public bool IsOpenedReadOnly(object document)
    {
        Calls.Add(new FakeOpenCall("IsOpenedReadOnly", ReferenceEquals(document, Opened) ? "opened" : "other"));
        if (ReadOnlyFailure != null)
        {
            throw ReadOnlyFailure;
        }

        return OpenedReadOnly;
    }

    public void CloseDoc(string path)
    {
        Calls.Add(new FakeOpenCall("CloseDoc", path));
        if (CloseFailure != null)
        {
            throw CloseFailure;
        }

        _open.Remove(path);
    }
}
