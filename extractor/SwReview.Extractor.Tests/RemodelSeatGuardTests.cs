using System;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using SwReview.Extractor.Guard;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// Owner decision 144A (feature 011 T163, research R11, contracts/guard.md section 8): the
/// re-modeler's pane seat calls SOLIDWORKS through a gate whose guard is an allowlist of its own -
/// exactly <c>ISldWorks.ActivateDoc3</c> and <c>ISldWorks.OpenDoc7</c>, matched ordinally - and every
/// other qualified key is refused. Since owner decision 148A (T182, research R12.1) the allowlist is
/// closed: the seat's five reads are on it, by the bare names the seat gates them under, and every other
/// name, bare or qualified, is refused, where a bare name was <see cref="ReadOnlyGuard"/>'s answer. The
/// guard widens neither <see cref="ReadOnlyGuard"/>, <see cref="RemodelGuard"/> nor
/// <see cref="DrawingOpenGuard"/>, and only the pane seat builds it. The seat's own calls, its open
/// options and its gate log are <c>SwRemodelSeatTests</c>' (in the add-in's suite).
/// </summary>
public class RemodelSeatGuardTests
{
    private static readonly string[] TheTwoKeys =
    {
        "ISldWorks.ActivateDoc3",
        "ISldWorks.OpenDoc7",
    };

    /// <summary>The reads <c>SwRemodelSeat</c> makes, by the bare names it gates them under (decision 148A).</summary>
    private static readonly string[] TheFiveReads =
    {
        "GetOpenDocumentByName",
        "GetPathName",
        "GetTitle",
        "ActiveDoc",
        "GetOpenDocSpec",
    };

    private readonly RemodelSeatGuard _guard = new RemodelSeatGuard();

    [Fact]
    public void TheAllowlistIsExactlyTheTwoKeysOfTheDecision()
    {
        Assert.Equal(
            TheTwoKeys.OrderBy(key => key, StringComparer.Ordinal),
            RemodelSeatGuard.AllowedKeys.OrderBy(key => key, StringComparer.Ordinal));
        Assert.Equal(RemodelSeatGuard.ActivateDocKey, TheTwoKeys[0]);
        Assert.Equal(RemodelSeatGuard.OpenDocKey, TheTwoKeys[1]);
    }

    [Theory]
    [InlineData("ISldWorks.ActivateDoc3")]
    [InlineData("ISldWorks.OpenDoc7")]
    [InlineData("  ISldWorks.OpenDoc7  ")]
    public void EachOfTheTwoKeysIsAllowed(string key)
    {
        _guard.Assert(key);
    }

    /// <summary>
    /// Any other qualified key is refused naming it: the other opens and activations, the closes, the
    /// writes the re-modeler makes under its own allowlist, a read spelled qualified, and the two keys
    /// in another case.
    /// </summary>
    [Theory]
    [InlineData("ISldWorks.OpenDoc6")]
    [InlineData("ISldWorks.OpenDoc")]
    [InlineData("ISldWorks.IOpenDoc5")]
    [InlineData("ISldWorks.ActivateDoc2")]
    [InlineData("ISldWorks.IActivateDoc3")]
    [InlineData("ISldWorks.CloseDoc")]
    [InlineData("ISldWorks.CloseAllDocuments")]
    [InlineData("ISldWorks.DocumentVisible")]
    [InlineData("ISldWorks.NewDocument")]
    [InlineData("IModelDoc2.Save3")]
    [InlineData("IModelDoc2.ForceRebuild3")]
    [InlineData("IModelDoc2.Close")]
    [InlineData("IModelDoc2.GetPathName")]
    [InlineData("IModelDocExtension.ReorderFeature")]
    [InlineData("isldworks.activatedoc3")]
    [InlineData("ISldWorks.opendoc7")]
    [InlineData("ISLDWORKS.OpenDoc7")]
    public void AnyOtherQualifiedKeyIsRefusedNamingIt(string key)
    {
        MutatingCallError refusal = Assert.Throws<MutatingCallError>(() => _guard.Assert(key));

        Assert.Equal(key, refusal.MemberName);
        Assert.Contains(key, refusal.Message, StringComparison.Ordinal);
    }

    /// <summary>
    /// Owner decision 148A (feature 011 T182): the reads on the list are exactly the five the seat
    /// makes - its lookup, a document's path and title, the active document and the open request - as
    /// <c>SwRemodelSeat</c> names them, bare. <c>SwRemodelSeatTests</c> holds the list to the members the
    /// seat's gate is asked about, way by way.
    /// </summary>
    [Fact]
    public void TheReadsOnTheListAreExactlyTheFiveTheSeatMakes()
    {
        Assert.Equal(
            TheFiveReads.OrderBy(read => read, StringComparer.Ordinal),
            RemodelSeatGuard.AllowedReads.OrderBy(read => read, StringComparer.Ordinal));
    }

    /// <summary>
    /// Decision 148A: each read on the list is a read - the read-only guard allows it - and a bare name,
    /// so the list can never name a writer the read-only guard refuses, nor a qualified key.
    /// </summary>
    [Fact]
    public void EveryReadOnTheListIsABareNameTheReadOnlyGuardAllows()
    {
        Assert.NotEmpty(RemodelSeatGuard.AllowedReads);
        foreach (string read in RemodelSeatGuard.AllowedReads)
        {
            Assert.False(CallKey.IsQualified(read), read + " is qualified");
            ReadOnlyGuard.Assert(read);
        }
    }

    /// <summary>
    /// Edited deliberately for decision 148A (feature 011 T182): it was
    /// <c>ABareReadIsAllowedExactlyAsTheReadOnlyGuardAllowsIt</c>, whose cases were the seat's five reads
    /// and <c>IsOpenedReadOnly</c>, a read the seat never makes; the closed allowlist refuses that one
    /// (<see cref="AnyOtherBareNameIsRefusedNamingItWhateverTheReadOnlyGuardAnswers"/>), and each of the five
    /// is allowed, the read-only guard allowing it too.
    /// </summary>
    [Theory]
    [InlineData("GetOpenDocumentByName")]
    [InlineData("GetPathName")]
    [InlineData("GetTitle")]
    [InlineData("ActiveDoc")]
    [InlineData("GetOpenDocSpec")]
    [InlineData("  GetPathName  ")]
    public void EachOfTheFiveReadsIsAllowed(string member)
    {
        ReadOnlyGuard.Assert(member);
        _guard.Assert(member);
    }

    /// <summary>
    /// Replaced deliberately for decision 148A (feature 011 T182): it was
    /// <c>ABareNameIsAnsweredExactlyAsTheReadOnlyGuardAnswersIt</c> - a bare name was the read-only guard's
    /// answer, so the bare <c>CloseDoc</c> the read-only guard leaves allowed passed this guard (research
    /// R11.7, finding 3). The allowlist is closed now: a bare name off it is refused naming it, whatever the
    /// read-only guard answers - the writers it leaves allowed (<c>CloseDoc</c>, <c>OpenDoc6</c>), the two keys'
    /// own bare names, the writers it refuses, a read the seat never makes, and a read of the list in another
    /// case.
    /// </summary>
    [Theory]
    [InlineData("CloseDoc")]
    [InlineData("OpenDoc6")]
    [InlineData("OpenDoc7")]
    [InlineData("ActivateDoc3")]
    [InlineData("Save3")]
    [InlineData("SaveAs")]
    [InlineData("CloseAllDocuments")]
    [InlineData("DocumentVisible")]
    [InlineData("ForceRebuild3")]
    [InlineData("NewDocument")]
    [InlineData("SetUserPreferenceToggle")]
    [InlineData("IsOpenedReadOnly")]
    [InlineData("GetDocuments")]
    [InlineData("GetTitle2")]
    [InlineData("getpathname")]
    [InlineData("GETOPENDOCUMENTBYNAME")]
    [InlineData("activedoc")]
    public void AnyOtherBareNameIsRefusedNamingItWhateverTheReadOnlyGuardAnswers(string member)
    {
        MutatingCallError refusal = Assert.Throws<MutatingCallError>(() => _guard.Assert(member));

        Assert.Equal(member, refusal.MemberName);
        Assert.Contains(member, refusal.Message, StringComparison.Ordinal);
    }

    /// <summary>
    /// Decision 148A: the cases above include the bare writers the read-only guard leaves allowed and the
    /// reads it allows, so the refusal is the closed list's and not the read-only guard's.
    /// </summary>
    [Theory]
    [InlineData("CloseDoc")]
    [InlineData("OpenDoc6")]
    [InlineData("IsOpenedReadOnly")]
    [InlineData("GetDocuments")]
    public void ANameTheReadOnlyGuardAllowsIsRefusedWhenTheSeatDoesNotMakeIt(string member)
    {
        ReadOnlyGuard.Assert(member);
        Assert.True(Refuses(() => _guard.Assert(member)), member);
    }

    /// <summary>
    /// Of the two keys only <c>ActivateDoc3</c> overrides a read-only denial (contracts/guard.md section
    /// 1's shared <c>ISldWorks</c> row): <c>OpenDoc7</c> is an exclusion of section 3, which the
    /// read-only guard leaves allowed for <c>remodel.open</c> and <c>probe remodel</c>'s reopen.
    /// </summary>
    [Fact]
    public void TheOnlyKeyWhoseBareNameTheReadOnlyGuardDeniesIsActivateDoc3()
    {
        Assert.Equal(
            new[] { "ISldWorks.ActivateDoc3" },
            RemodelSeatGuard.AllowedKeys.Where(key => Refuses(() => ReadOnlyGuard.Assert(CallKey.BareName(key)))));
    }

    /// <summary>
    /// It widens no other guard: the read-only guard refuses <c>ActivateDoc3</c> in both spellings, and
    /// the two other allowlist guards refuse both keys, which are on neither of their lists.
    /// </summary>
    [Fact]
    public void TheGuardWidensNoOtherGuard()
    {
        Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert("ActivateDoc3"));
        Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert("ISldWorks.ActivateDoc3"));
        foreach (string key in TheTwoKeys)
        {
            Assert.DoesNotContain(key, RemodelGuard.AllowedKeys);
            Assert.DoesNotContain(key, DrawingOpenGuard.AllowedKeys);
            Assert.Throws<MutatingCallError>(() => new RemodelGuard().Assert(key));
            Assert.Throws<MutatingCallError>(() => new DrawingOpenGuard().Assert(key));
        }
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public void NoMemberIsAnArgumentError(string? member)
    {
        Assert.Throws<ArgumentException>(() => _guard.Assert(member!));
    }

    /// <summary>
    /// Its scope is the one class built with it: the pane seat, <c>SwRemodelSeat</c>, which opens and
    /// activates the run's copy only. A second site would carry the two keys to a gate the decision never
    /// reviewed, so no product file but the seat's names the guard - however it is built, <c>new()</c>
    /// included - or the seat's gate factory. Widened on the decision's review (T173): it read
    /// <c>new RemodelSeatGuard(</c> alone, and another add-in file could have built the seat's gate
    /// through <c>SwRemodelSeat.Gate</c>.
    /// </summary>
    [Fact]
    public void OnlyThePaneSeatNamesTheGuardOrItsGate()
    {
        var named = new Regex(
            @"\bRemodelSeatGuard\b|\bSwRemodelSeat\s*\.\s*Gate\b|\busing\s+static\s+[\w.]*\bSwRemodelSeat\b",
            RegexOptions.CultureInvariant);
        string root = DrawingFamilyReadAuditTests.ExtractorRoot();
        var sites = DrawingFamilyReadAuditTests.ProductSourceFiles()
            .Where(file => File.ReadAllLines(file)
                .Any(line => !DrawingFamilyReadAuditTests.IsWholeLineComment(line) && named.IsMatch(line)))
            .Select(file => file.Substring(root.Length).TrimStart('\\', '/').Replace('\\', '/'))
            .ToList();

        Assert.Equal(new[] { DrawingFamilyReadAuditTests.PaneSeatFile }, sites);
        Assert.Contains(
            "new SwGate(new CircuitBreaker(), new RemodelSeatGuard())",
            File.ReadAllText(Path.Combine(root, DrawingFamilyReadAuditTests.PaneSeatFile)),
            StringComparison.Ordinal);
    }

    /// <summary>Whether <paramref name="assert"/> refuses: <see cref="GuardSweep.Refuses"/>, the one copy of the rule.</summary>
    private static bool Refuses(Action assert) => GuardSweep.Refuses(_ => assert(), string.Empty);
}
