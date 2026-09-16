namespace SwReview.Extractor.Dump;

/// <summary>
/// What <c>IFeature.IsSuppressed2</c> answered, read without guessing (T006).
///
/// The call takes a configuration option and answers with a VARIANT holding one flag per
/// configuration it was asked about, so interop hands it back as a bare bool, a bool[], or
/// an object[] of boxed bools depending on the build. Only the first flag is ours - the
/// caller asks for <c>swThisConfiguration</c> - and any shape carrying no flag at all is
/// <c>null</c>, never <c>false</c>: the caller turns null into a recorded gap, and a mate
/// wrongly reported unsuppressed would silently put an edge back into the mate graph the
/// chain-depth rule walks (constitution Principle I).
///
/// Pure and public so the branches are testable; the dumper it serves needs a SOLIDWORKS
/// seat, this does not.
/// </summary>
public static class SuppressionAnswer
{
    /// <summary>The first flag of an IsSuppressed2 answer, or null when it carried none.</summary>
    public static bool? FirstFlag(object? answer)
    {
        switch (answer)
        {
            case bool single:
                return single;
            case bool[] flags when flags.Length > 0:
                return flags[0];
            case object[] boxed when boxed.Length > 0 && boxed[0] is bool first:
                return first;
            default:
                return null;
        }
    }
}
