using System;
using System.Collections;
using System.Collections.Generic;

namespace SwReview.AddIn.Terminal;

/// <summary>
/// The Terminal tab's published tool names, counted, indexed and enumerated without exposing a mutable
/// collection interface (owner decision 160A). The private copy keeps the source array private too.
/// </summary>
internal sealed class ReadOnlyToolList : IReadOnlyList<string>
{
    private readonly string[] _tools;

    public ReadOnlyToolList(params string[] tools)
    {
        _tools = (string[])(tools ?? throw new ArgumentNullException(nameof(tools))).Clone();
    }

    public int Count => _tools.Length;

    public string this[int index] => _tools[index];

    public IEnumerator<string> GetEnumerator() => ((IEnumerable<string>)_tools).GetEnumerator();

    IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
}
