using System;

namespace SwReview.Extractor.PersistRefs;

/// <summary>
/// Raised when a persistent reference is missing, empty or unreadable. Callers turn this
/// into a <see cref="Ir.Gap"/>; they never write a placeholder reference (the IR schema
/// gives persist_ref a minLength of 1, and a finding with a broken locator is worse than a
/// recorded gap).
/// </summary>
[Serializable]
public class PersistRefError : Exception
{
    public PersistRefError(string message)
        : base(message)
    {
    }

    public PersistRefError(string message, Exception inner)
        : base(message, inner)
    {
    }
}

/// <summary>
/// The byte array <c>IModelDocExtension.GetPersistReference3</c> returns, and the base64
/// string the IR stores. Nothing else; resolving a reference back to an entity needs
/// SOLIDWORKS and lives in <see cref="PersistRefService"/>.
///
/// References are never compared byte-wise (research R12: the bytes for one entity can
/// differ between calls); comparison goes through
/// <c>IModelDocExtension.IsSamePersistentID</c>.
/// </summary>
public static class PersistRefCodec
{
    /// <summary>Base64 of a non-empty reference. Throws for an empty or null array.</summary>
    public static string Encode(byte[] bytes)
    {
        if (bytes == null)
        {
            throw new ArgumentNullException(nameof(bytes));
        }

        if (bytes.Length == 0)
        {
            throw new PersistRefError(
                "GetPersistReference3 returned an empty reference; the entity cannot be located later.");
        }

        return Convert.ToBase64String(bytes);
    }

    /// <summary>
    /// Encode without throwing, for the traversal paths that record a gap and move on.
    /// </summary>
    public static bool TryEncode(byte[]? bytes, out string? encoded)
    {
        if (bytes == null || bytes.Length == 0)
        {
            encoded = null;
            return false;
        }

        encoded = Convert.ToBase64String(bytes);
        return true;
    }

    /// <summary>The reference bytes behind a base64 string. Throws for anything unusable.</summary>
    public static byte[] Decode(string base64)
    {
        if (string.IsNullOrWhiteSpace(base64))
        {
            throw new PersistRefError("A base64 persistent reference is required.");
        }

        byte[] bytes;
        try
        {
            bytes = Convert.FromBase64String(base64.Trim());
        }
        catch (FormatException ex)
        {
            throw new PersistRefError("The persistent reference is not valid base64.", ex);
        }

        if (bytes.Length == 0)
        {
            throw new PersistRefError("The persistent reference decoded to zero bytes.");
        }

        return bytes;
    }

    /// <summary>
    /// Encodes the value interop hands back from <c>GetPersistReference3</c>, which is
    /// declared as <c>object</c> and carries a boxed <c>byte[]</c>.
    /// </summary>
    public static string EncodeComValue(object? comValue)
    {
        if (comValue == null)
        {
            throw new PersistRefError(
                "GetPersistReference3 returned null; the entity has no persistent reference.");
        }

        if (comValue is byte[] bytes)
        {
            return Encode(bytes);
        }

        throw new PersistRefError(
            $"GetPersistReference3 returned {comValue.GetType().Name}, not a byte array.");
    }
}
