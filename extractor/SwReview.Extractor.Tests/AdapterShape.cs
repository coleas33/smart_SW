using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text.RegularExpressions;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Tests;

/// <summary>
/// The shape checks every ungated SOLIDWORKS-facing remodel class shares (feature 004, T152 and
/// T153's amendment): the bridge gates the adapter from outside, so the adapter takes and holds no
/// <see cref="SwGate"/>, <see cref="ICallGuard"/> or <see cref="RemodelScope"/>, names none of them
/// in its code, and takes no document path it did not create.
///
/// Written once and shared: lane A's shared classes are checked with it here, and
/// <c>SwReview.AddIn.Tests</c> compiles this same file (a link in its project file) for the seat
/// adapter's classes, so the two suites check one rule.
/// </summary>
internal static class AdapterShape
{
    private const BindingFlags Everything =
        BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;

    /// <summary>The three types an ungated adapter never takes or holds.</summary>
    public static readonly IReadOnlyList<Type> ForbiddenTypes = new[] { typeof(SwGate), typeof(ICallGuard), typeof(RemodelScope) };

    /// <summary>What an ungated adapter's code never says: a gate, a guard, a scope, or a gated call.</summary>
    public static readonly IReadOnlyList<string> GatedCallTokens = new[]
    {
        "SwGate", "ICallGuard", "RemodelScope", "RemodelGuard", ".Call(", ".CallOptional(", ".Assert(",
    };

    /// <summary>A parameter name that could carry a document's path.</summary>
    public static readonly Regex PathLike = new Regex("path|file|document|title", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

    /// <summary>Every place <paramref name="type"/> could take or hold a forbidden type, named.</summary>
    public static List<string> MentionsOfForbiddenTypes(Type type)
    {
        var found = new List<string>();

        for (Type? current = type; current != null && current != typeof(object); current = current.BaseType)
        {
            found.AddRange(current.GetFields(Everything).Where(field => Mentions(field.FieldType)).Select(field => "field " + field.Name));
            found.AddRange(current.GetProperties(Everything).Where(property => Mentions(property.PropertyType)).Select(property => "property " + property.Name));

            IEnumerable<MethodBase> methods = current.GetMethods(Everything).Cast<MethodBase>().Concat(current.GetConstructors(Everything));
            foreach (MethodBase method in methods)
            {
                found.AddRange(method.GetParameters().Where(parameter => Mentions(parameter.ParameterType)).Select(parameter => $"{method.Name}({parameter.Name})"));
                if (method is MethodInfo info && Mentions(info.ReturnType))
                {
                    found.Add(method.Name + " returns " + info.ReturnType.Name);
                }
            }
        }

        return found;
    }

    /// <summary>Every parameter of every method and constructor <paramref name="type"/> declares, with the member it belongs to.</summary>
    public static IEnumerable<(MethodBase Member, ParameterInfo Parameter)> DeclaredParameters(Type type) =>
        type.GetMethods(Everything)
            .Cast<MethodBase>()
            .Concat(type.GetConstructors(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
            .SelectMany(member => member.GetParameters().Select(parameter => (member, parameter)));

    /// <summary>Every field <paramref name="type"/> and its base classes declare.</summary>
    public static IEnumerable<FieldInfo> AllFields(Type type)
    {
        for (Type? current = type; current != null && current != typeof(object); current = current.BaseType)
        {
            foreach (FieldInfo field in current.GetFields(Everything))
            {
                yield return field;
            }
        }
    }

    /// <summary>Source text with its comment lines (<c>//</c> and <c>///</c>) left out.</summary>
    public static string CodeOutsideComments(string source) =>
        string.Join(
            "\n",
            source.Replace("\r\n", "\n")
                .Split('\n')
                .Where(line => !line.TrimStart().StartsWith("//", StringComparison.Ordinal)));

    /// <summary>A forbidden type, or one built from it: an array, a by-ref, or a generic argument (a <c>Func&lt;SwGate&gt;</c>).</summary>
    private static bool Mentions(Type type)
    {
        if (type.HasElementType)
        {
            return Mentions(type.GetElementType()!);
        }

        if (type.IsGenericType && type.GetGenericArguments().Any(Mentions))
        {
            return true;
        }

        return ForbiddenTypes.Any(forbidden => forbidden.IsAssignableFrom(type));
    }
}
