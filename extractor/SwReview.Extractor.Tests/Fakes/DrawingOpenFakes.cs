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

    public object AlreadyOpen(string path)
    {
        var document = new object();
        _open[path] = document;
        return document;
    }

    public object? OpenDocument(string path)
    {
        Calls.Add(new FakeOpenCall("OpenDocument", path));
        if (!_open.TryGetValue(path, out object? document))
        {
            return null;
        }

        if (ReferenceEquals(document, Opened))
        {
            return AfterOpenAnswersNothing ? null : AfterOpenAnswer ?? document;
        }

        return document;
    }

    public void DocumentVisible(bool visible, int documentType) =>
        Calls.Add(new FakeOpenCall("DocumentVisible", visible, documentType));

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

    public void CloseDoc(string path)
    {
        Calls.Add(new FakeOpenCall("CloseDoc", path));
        _open.Remove(path);
    }
}
