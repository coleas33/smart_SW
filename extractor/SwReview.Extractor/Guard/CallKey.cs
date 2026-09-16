using System;

namespace SwReview.Extractor.Guard;

/// <summary>
/// T041. The key a remodel <b>write</b> call site hands the gate: <c>Interface.Member</c>.
///
/// Bare member names collide, and both halves of the collision are real on 2024 SP5:
/// <c>ICustomPropertyManager.Delete2(String)</c> - the session-tag delete - is refused today
/// because <see cref="ReadOnlyGuard"/> denies the bare name <c>Delete2</c>, which was written
/// for <c>IEntity.Delete2</c>; and an allowlist entry spelled <c>"Add3"</c> would silently
/// permit <c>ICustomPropertyManager.Add3</c> as well as <c>IEquationMgr.Add3</c>. The
/// interface-qualified form is what lets <see cref="RemodelGuard"/> answer per interface
/// (contracts/guard-allowlist.md, "Keys are interface-qualified").
///
/// Only the remodel family's write call sites use qualified keys. The reviewer's existing
/// <c>SwGate.Call("GetChildren", ...)</c> sites, and the remodel family's own read call sites,
/// keep bare names, so <see cref="BareName"/> is the identity on an unqualified key and the
/// guard's delegation to <see cref="ReadOnlyGuard"/> refuses exactly what it refused before.
/// </summary>
public static class CallKey
{
    /// <summary>The one character that separates the interface from the member.</summary>
    public const char Separator = '.';

    /// <summary>
    /// Builds <c>Interface.Member</c>. Both parts are required and neither may itself carry
    /// the separator, so a key always has exactly one.
    /// </summary>
    public static string QualifiedKey(string interfaceName, string memberName)
    {
        string iface = RequirePart(interfaceName, nameof(interfaceName));
        string member = RequirePart(memberName, nameof(memberName));

        return iface + Separator + member;
    }

    /// <summary>
    /// The member half of a qualified key, or the whole key when it is a bare member name -
    /// which is what the read call sites and the reviewer's existing gate sites pass.
    /// </summary>
    public static string BareName(string key)
    {
        string trimmed = RequireKey(key);
        int separator = trimmed.LastIndexOf(Separator);

        return separator < 0 ? trimmed : trimmed.Substring(separator + 1);
    }

    /// <summary>The interface half of a qualified key. A bare key is a programming error.</summary>
    public static string InterfaceName(string key)
    {
        string trimmed = AssertQualified(key);

        return trimmed.Substring(0, trimmed.LastIndexOf(Separator));
    }

    /// <summary>
    /// True when the key names an interface and a member, both non-empty.
    /// </summary>
    public static bool IsQualified(string key)
    {
        if (string.IsNullOrWhiteSpace(key))
        {
            return false;
        }

        string trimmed = key.Trim();
        int separator = trimmed.LastIndexOf(Separator);

        return separator > 0 && separator < trimmed.Length - 1;
    }

    /// <summary>
    /// The guard rail for a remodel write call site: a bare key could never have been on the
    /// interface-qualified allowlist, so the call would silently take the read-only path
    /// instead of being judged. That is a programming error, not a refusal.
    /// </summary>
    public static string AssertQualified(string key)
    {
        if (!IsQualified(key))
        {
            string described = string.IsNullOrWhiteSpace(key) ? "(no key)" : key.Trim();
            throw new ArgumentException(
                $"A remodel write call site needs an interface-qualified key such as "
                + $"\"IModelDoc2.Save3\"; got \"{described}\".",
                nameof(key));
        }

        return key.Trim();
    }

    private static string RequirePart(string part, string parameterName)
    {
        if (string.IsNullOrWhiteSpace(part))
        {
            throw new ArgumentException("An interface name and a member name are required.", parameterName);
        }

        string trimmed = part.Trim();
        if (trimmed.IndexOf(Separator) >= 0)
        {
            throw new ArgumentException(
                $"'{trimmed}' may not contain '{Separator}': a call key is exactly one interface "
                + "and one member.",
                parameterName);
        }

        return trimmed;
    }

    private static string RequireKey(string key)
    {
        if (string.IsNullOrWhiteSpace(key))
        {
            throw new ArgumentException("A call key is required.", nameof(key));
        }

        return key.Trim();
    }
}
