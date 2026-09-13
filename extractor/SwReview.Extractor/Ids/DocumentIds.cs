using System;
using System.Security.Cryptography;
using System.Text;

namespace SwReview.Extractor.Ids;

/// <summary>
/// Document and design ids derived from the file path, so the same file gets the same id
/// in every dump and two packages of one design can be compared field by field.
///
/// SHA-1 is used as a short, stable hash of a path, never as a security primitive.
/// </summary>
public static class DocumentIds
{
    private const int HexLength = 12;

    /// <summary><c>doc:</c> plus the first 12 hex digits of SHA-1 over the normalized path.</summary>
    public static string For(string path) => "doc:" + Hash(path);

    /// <summary><c>dsn:</c> plus the same hash of the root document's path.</summary>
    public static string DesignId(string rootDocumentPath) => "dsn:" + Hash(rootDocumentPath);

    /// <summary>
    /// Lowercase with backslash separators. SOLIDWORKS reports the same file with either
    /// separator and either case depending on how it was referenced; the id must not.
    /// GetFullPath is deliberately not called - it would resolve against the extractor's
    /// working directory and can throw on a UNC or vault path we only need to hash.
    /// </summary>
    private static string Hash(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new ArgumentException("A document path is required to derive an id.", nameof(path));
        }

        string normalized = path.Trim().Replace('/', '\\').ToLowerInvariant();

        using (var sha1 = SHA1.Create())
        {
            byte[] digest = sha1.ComputeHash(Encoding.UTF8.GetBytes(normalized));
            var hex = new StringBuilder(HexLength);
            for (int i = 0; i < HexLength / 2; i++)
            {
                hex.Append(digest[i].ToString("x2"));
            }

            return hex.ToString();
        }
    }
}
