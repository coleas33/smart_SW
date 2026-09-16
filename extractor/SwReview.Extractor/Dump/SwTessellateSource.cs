using System;
using System.Collections.Generic;
using System.IO;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Dump;

/// <summary>
/// T097, lever 10a. The SOLIDWORKS side of <c>tessellate</c>.
///
/// It writes no mesh of its own: it hands one traversed component to
/// <see cref="IMeshSource.DumpComponent"/>, which is the same <c>ExportBody</c> the dump
/// calls. That is the whole point of the class - a second tessellator with its own chord
/// tolerance would make a clearance answer depend on how the mesh arrived
/// (contracts/levers.md, lever 10a; FR-090).
///
/// <b>One scope for the life of the bridge.</b> The scope carries the body-id allocator, so
/// two fetches in one review cannot both call their body <c>bod:0001</c>, and it carries the
/// component ids the traversal allocated, which are the ids the client reads out of
/// package.json. Its gap list therefore grows across calls, so each answer carries only the
/// gaps that call recorded.
/// </summary>
public sealed class SwTessellateSource : ITessellateSource
{
    private readonly IMeshSource _meshes;
    private readonly DumpScope _scope;

    public SwTessellateSource(IMeshSource meshes, DumpScope scope)
    {
        _meshes = meshes ?? throw new ArgumentNullException(nameof(meshes));
        _scope = scope ?? throw new ArgumentNullException(nameof(scope));
    }

    public TessellateCommandResult Tessellate(string componentId, string packageDirectory)
    {
        if (string.IsNullOrWhiteSpace(componentId))
        {
            throw new ArgumentException("A component id is required.", nameof(componentId));
        }

        if (string.IsNullOrWhiteSpace(packageDirectory))
        {
            throw new ArgumentException(
                "The host's package directory is required.", nameof(packageDirectory));
        }

        var result = new TessellateCommandResult();
        int before = _scope.Gaps.Count;

        ScopedComponent? component = Find(componentId);
        if (component == null)
        {
            // Not an empty answer: an empty answer reads as "this component has no body",
            // which is a clear nothing established (constitution Principle I).
            _scope.Gaps.Add(
                GapKind.NotExtracted,
                "body",
                null,
                $"'{componentId}' is not a component this bridge traversed, so no mesh "
                + "could be written for it.",
                null);
        }
        else
        {
            string meshDirectory = Path.Combine(
                packageDirectory, PackageWriter.MeshDirectoryName);

            foreach (BodyRef body in _meshes.DumpComponent(_scope, component, meshDirectory))
            {
                result.Bodies.Add(body);
                result.Paths.Add(
                    Path.GetFullPath(
                        Path.Combine(
                            packageDirectory,
                            body.MeshFile.Replace('/', Path.DirectorySeparatorChar))));
            }
        }

        IReadOnlyList<Gap> gaps = _scope.Gaps.Gaps;
        for (int i = before; i < gaps.Count; i++)
        {
            result.Gaps.Add(gaps[i]);
        }

        return result;
    }

    /// <summary>
    /// The traversed component carrying <paramref name="componentId"/>, or null.
    ///
    /// By id rather than by <c>DumpScope.Find</c>'s instance key, because the id is what the
    /// client has: it read it out of package.json, and the dump and this traversal allocate
    /// ids the same way (<see cref="PackageWriter.ScopeFor"/>).
    /// </summary>
    private ScopedComponent? Find(string componentId)
    {
        foreach (ScopedComponent component in _scope.Components)
        {
            if (string.Equals(component.Id, componentId, StringComparison.Ordinal))
            {
                return component;
            }
        }

        return null;
    }
}
