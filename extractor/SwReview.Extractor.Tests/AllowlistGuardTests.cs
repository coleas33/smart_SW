using System;
using System.Collections.Generic;
using System.Linq;
using SwReview.Extractor.Guard;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// Owner decision 151A (feature 011 T200, 2026-10-20; research R13.1): the three allowlist guards -
/// <see cref="DrawingOpenGuard"/>, <see cref="RemodelSeatGuard"/> and <see cref="RemodelGuard"/> - answer
/// every name the generated tables and the product use exactly as they did before the decision gave
/// them one shared rule. "Before" is each guard's own code as it stood at <c>5685def</c>, kept here
/// verbatim as the oracle (<see cref="Before151A"/>); so a refactor that changes one answer - a name
/// allowed that was refused or refused that was allowed, a refusal naming another member or in other
/// words, or a missing name answered otherwise - fails here, naming the guard and the name.
///
/// Written before the code moved, and green against it. The oracle reads each guard's own lists, as the
/// guard did, so a list changed deliberately later changes both sides alike; the lists themselves are
/// pinned exactly by each guard's own class (<see cref="DrawingOpenGuardTests"/>,
/// <see cref="RemodelSeatGuardTests"/>, <see cref="RemodelGuardTests"/>). And the read-only guard's
/// answer, which two of the three hand their bare names to, is read live on both sides, so a denial a
/// later decision adds moves neither.
/// </summary>
public class AllowlistGuardAnswersTests
{
    /// <summary>Each guard under test, built as the product builds it, beside its answer before decision 151A.</summary>
    public static IEnumerable<object[]> EveryAllowlistGuard() => new[]
    {
        new object[] { nameof(DrawingOpenGuard) },
        new object[] { nameof(RemodelSeatGuard) },
        new object[] { nameof(RemodelGuard) },
    };

    /// <summary>
    /// Every name the generated tables and the product use, each in four spellings - as written, in
    /// upper case, in lower case and with spaces around it - and the names that are not names: the
    /// denial tables, bare and qualified with the interface each row names, and the names each leaves
    /// allowed; what the read-only guard denies; every string literal of the product source, which
    /// holds every member a call site gates and every key it names; each allowlist guard's own keys,
    /// reads and refusals, bare and qualified; and blank or malformed names.
    /// </summary>
    [Theory]
    [MemberData(nameof(EveryAllowlistGuard))]
    public void EveryNameTheTablesAndTheProductUseIsAnsweredAsBeforeDecision151A(string guard)
    {
        IReadOnlyCollection<string?> names = NamesTheTablesAndTheProductUse();

        Assert.True(names.Count > 20000, "The names gathered are too few to pin anything: " + names.Count);
        AssertAnsweredAsBefore(guard, names);
    }

    /// <summary>
    /// The same, for every member of the 34 interfaces the generated tables are written against
    /// (<see cref="DocumentWriteFamilyTests.Interfaces"/>), bare and qualified with its interface, in the
    /// same four spellings: the names the tables were generated from, readers and writers alike. Only
    /// metadata is read; SOLIDWORKS is never started.
    /// </summary>
    [RemodelInteropManifestTests.InteropAssembliesPresentFact]
    public void EveryMemberOfTheInterfacesTheTablesAreWrittenAgainstIsAnsweredAsBeforeDecision151A()
    {
        var names = new HashSet<string?>(StringComparer.Ordinal);
        foreach (string face in DocumentWriteFamilyTests.Interfaces)
        {
            foreach (string member in DrawingFamilyCompletenessTests.MethodNames(face))
            {
                AddSpellings(names, member);
                AddSpellings(names, face + "." + member);
            }
        }

        Assert.True(names.Count > 20000, "The interop's members gathered are too few to pin anything: " + names.Count);
        foreach (object[] guard in EveryAllowlistGuard())
        {
            AssertAnsweredAsBefore((string)guard[0], names);
        }
    }

    /// <summary>
    /// The oracle itself, against the guards' own pinned cases: each guard's keys pass, a key in
    /// another case is refused naming it, a missing name is an argument error, and each answers its
    /// bare names as its class says - so a mistake in the copy below cannot pass by agreeing with a
    /// mistake in the guard.
    /// </summary>
    [Fact]
    public void TheOracleGivesTheAnswersTheGuardsOwnClassesPin()
    {
        Assert.Equal("allowed", Answer(Before151A.DrawingOpenGuardAssert, "ISldWorks.OpenDoc6"));
        Assert.StartsWith("refused isldworks.opendoc6 | ", Answer(Before151A.DrawingOpenGuardAssert, "isldworks.opendoc6"), StringComparison.Ordinal);
        Assert.Equal("allowed", Answer(Before151A.DrawingOpenGuardAssert, "GetPathName"));
        Assert.StartsWith("refused Save3 | ", Answer(Before151A.DrawingOpenGuardAssert, "Save3"), StringComparison.Ordinal);

        Assert.Equal("allowed", Answer(Before151A.RemodelSeatGuardAssert, "  ISldWorks.ActivateDoc3  "));
        Assert.Equal("allowed", Answer(Before151A.RemodelSeatGuardAssert, "GetTitle"));
        Assert.StartsWith("refused CloseDoc | ", Answer(Before151A.RemodelSeatGuardAssert, "CloseDoc"), StringComparison.Ordinal);
        Assert.StartsWith("refused IModelDoc2.GetPathName | ", Answer(Before151A.RemodelSeatGuardAssert, "IModelDoc2.GetPathName"), StringComparison.Ordinal);

        Assert.Equal("allowed", Answer(Before151A.RemodelGuardAssert, "ICustomPropertyManager.Delete2"));
        Assert.StartsWith("refused EditUndo2 | ", Answer(Before151A.RemodelGuardAssert, "EditUndo2"), StringComparison.Ordinal);
        Assert.Contains("excluded", Answer(Before151A.RemodelGuardAssert, "IModelDoc2.EditUndo2"), StringComparison.Ordinal);
        Assert.Equal("allowed", Answer(Before151A.RemodelGuardAssert, "DeleteConfiguration2"));
        Assert.StartsWith("refused IModelDoc2.DeleteConfiguration2 | ", Answer(Before151A.RemodelGuardAssert, "IModelDoc2.DeleteConfiguration2"), StringComparison.Ordinal);

        foreach (Action<string> before in new Action<string>[] { Before151A.DrawingOpenGuardAssert, Before151A.RemodelSeatGuardAssert, Before151A.RemodelGuardAssert })
        {
            Assert.StartsWith("argument interopMemberName | ", Answer(before, null), StringComparison.Ordinal);
            Assert.StartsWith("argument interopMemberName | ", Answer(before, "   "), StringComparison.Ordinal);
        }
    }

    private static void AssertAnsweredAsBefore(string guard, IReadOnlyCollection<string?> names)
    {
        ICallGuard after = Build(guard);
        Action<string> before = BeforeOf(guard);

        var differ = names
            .Select(name => (Name: name, After: Answer(after.Assert, name), Before: Answer(before, name)))
            .Where(answer => !string.Equals(answer.After, answer.Before, StringComparison.Ordinal))
            .Take(20)
            .Select(answer => $"'{answer.Name}': now {answer.After}; before {answer.Before}")
            .ToList();

        Assert.True(
            differ.Count == 0,
            $"{guard} answers otherwise than before decision 151A ({names.Count} names):\n" + string.Join("\n", differ));
    }

    private static ICallGuard Build(string guard) => guard switch
    {
        nameof(DrawingOpenGuard) => new DrawingOpenGuard(),
        nameof(RemodelSeatGuard) => new RemodelSeatGuard(),
        nameof(RemodelGuard) => new RemodelGuard(),
        _ => throw new ArgumentOutOfRangeException(nameof(guard), guard, "Not an allowlist guard."),
    };

    private static Action<string> BeforeOf(string guard) => guard switch
    {
        nameof(DrawingOpenGuard) => Before151A.DrawingOpenGuardAssert,
        nameof(RemodelSeatGuard) => Before151A.RemodelSeatGuardAssert,
        nameof(RemodelGuard) => Before151A.RemodelGuardAssert,
        _ => throw new ArgumentOutOfRangeException(nameof(guard), guard, "Not an allowlist guard."),
    };

    /// <summary>
    /// A guard's whole answer to a name: allowed; refused, with the member the refusal names and its
    /// words; or an argument error, with the parameter and its words. Any other exception is no answer
    /// a guard gives, and fails the test where it is thrown.
    /// </summary>
    internal static string Answer(Action<string> assert, string? name)
    {
        try
        {
            assert(name!);
            return "allowed";
        }
        catch (MutatingCallError refusal)
        {
            return "refused " + refusal.MemberName + " | " + refusal.Message;
        }
        catch (ArgumentException missing)
        {
            return "argument " + missing.ParamName + " | " + missing.Message;
        }
    }

    /// <summary>The names <see cref="EveryNameTheTablesAndTheProductUseIsAnsweredAsBeforeDecision151A"/> reads.</summary>
    internal static IReadOnlyCollection<string?> NamesTheTablesAndTheProductUse()
    {
        var names = new HashSet<string?>(StringComparer.Ordinal);

        // The generated tables - feature 011's and decision 21A's - bare and qualified with the interface
        // each row names, and the names each leaves allowed.
        foreach ((string Family, string[] Members) row in DrawingFamilyDenylistTests.Table)
        {
            foreach (string member in row.Members)
            {
                AddSpellings(names, member);
                AddSpellings(names, DrawingFamilyDenylistTests.InterfaceOf(row) + "." + member);
            }
        }

        foreach ((string Interface, string Member) row in CreationFamilyDenylistTests.Rows())
        {
            AddSpellings(names, row.Member);
            AddSpellings(names, row.Interface + "." + row.Member);
        }

        AddAll(names, DrawingFamilyDenylistTests.ExcludedMembers);
        AddAll(names, CreationFamilyDenylistTests.ExcludedMembers);

        // The hand-kept tables beside them - features 006 and 010, decision 17A - and what the read-only
        // guard denies by name and by prefix.
        AddAll(names, StandardsDenylistTests.ExpectedMembers);
        AddAll(names, MechanicalChecksDenylistTests.ExpectedMembers);
        AddAll(names, ImportRepairDenylistTests.QualifiedKeys);
        AddAll(names, ImportRepairDenylistTests.ExpectedMembers);
        AddAll(names, ImportRepairDenylistTests.LeftOpenNames);
        AddAll(names, ReadOnlyGuard.DeniedMembers);
        AddAll(names, ReadOnlyGuard.DeniedPrefixes);

        // Every string literal of the product source: every member a call site gates, by the spelling
        // it gates it under, and every key it names.
        AddAll(names, DrawingFamilyReadAuditTests.Literals().Select(literal => literal.Literal));

        // Each allowlist guard's own names - its keys and their bare names, its reads, and what it
        // refuses by name, bare and qualified - and the other guards' exemptions.
        foreach (string key in DrawingOpenGuard.AllowedKeys.Concat(RemodelSeatGuard.AllowedKeys).Concat(RemodelGuard.AllowedKeys))
        {
            AddSpellings(names, key);
            AddSpellings(names, CallKey.BareName(key));
            AddSpellings(names, "IModelDoc2." + CallKey.BareName(key));
        }

        AddAll(names, RemodelSeatGuard.AllowedReads);
        AddAll(names, RemodelSeatGuard.AllowedReads.Select(read => "IModelDoc2." + read));
        AddAll(names, RemodelGuard.ExcludedMembers);
        AddAll(names, RemodelGuard.ExcludedMembers.Select(member => "IModelDocExtension." + member));
        AddAll(names, RemodelProbeGuard.ThrowawayPartCreationMembers);

        // Names that are not names, or not well formed.
        foreach (string? malformed in new[]
                 {
                     null, string.Empty, " ", "   ", "\t", "\r\n", ".", "..", "ISldWorks.", ".OpenDoc7",
                     "ISldWorks..OpenDoc7", "ISldWorks.OpenDoc7.", "ISldWorks .OpenDoc7", "ISldWorks. OpenDoc7",
                     "I.S.OpenDoc7", "ISldWorks.OpenDoc7\t", "\tGetTitle",
                 })
        {
            names.Add(malformed);
        }

        return names;
    }

    private static void AddAll(HashSet<string?> names, IEnumerable<string> each)
    {
        foreach (string name in each)
        {
            AddSpellings(names, name);
        }
    }

    /// <summary>A name as written, in upper case, in lower case, and with spaces around it.</summary>
    private static void AddSpellings(HashSet<string?> names, string name)
    {
        names.Add(name);
        names.Add(name.ToUpperInvariant());
        names.Add(name.ToLowerInvariant());
        names.Add("  " + name + "  ");
    }

    /// <summary>
    /// The three guards' own <c>Assert</c> as each stood at <c>5685def</c>, before decision 151A, copied
    /// verbatim but for reading the guard's lists through its public members (its own sets, matched as it
    /// matched them). This is the record of "before"; it changes only if a later decision changes a
    /// guard's rule on purpose, and says so.
    /// </summary>
    internal static class Before151A
    {
        internal static void DrawingOpenGuardAssert(string interopMemberName)
        {
            if (string.IsNullOrWhiteSpace(interopMemberName))
            {
                throw new ArgumentException("An interop member name is required.", nameof(interopMemberName));
            }

            string key = interopMemberName.Trim();

            if (DrawingOpenGuard.AllowedKeys.Contains(key, StringComparer.Ordinal))
            {
                return;
            }

            if (CallKey.IsQualified(key))
            {
                throw new MutatingCallError(
                    key,
                    $"{key} is not on the confirmed drawing's allowlist ({DrawingOpenGuard.DocumentVisibleKey}, {DrawingOpenGuard.OpenDocKey}, "
                    + $"{DrawingOpenGuard.CloseDocKey}; specs/004-resilient-remodeler/contracts/guard-allowlist.md).");
            }

            // A bare member name is a read call site. The read-only rules apply to it unchanged.
            ReadOnlyGuard.Assert(key);
        }

        internal static void RemodelSeatGuardAssert(string interopMemberName)
        {
            if (string.IsNullOrWhiteSpace(interopMemberName))
            {
                throw new ArgumentException("An interop member name is required.", nameof(interopMemberName));
            }

            string key = interopMemberName.Trim();

            if (RemodelSeatGuard.AllowedKeys.Contains(key, StringComparer.Ordinal)
                || RemodelSeatGuard.AllowedReads.Contains(key, StringComparer.Ordinal))
            {
                return;
            }

            throw new MutatingCallError(
                key,
                $"{key} is not on the re-modeler pane seat's allowlist, which holds the seat's own calls and "
                + $"nothing else: {RemodelSeatGuard.ActivateDocKey}, {RemodelSeatGuard.OpenDocKey} and the reads "
                + string.Join(", ", RemodelSeatGuard.AllowedReads)
                + " (specs/004-resilient-remodeler/contracts/guard-allowlist.md).");
        }

        internal static void RemodelGuardAssert(string interopMemberName)
        {
            if (string.IsNullOrWhiteSpace(interopMemberName))
            {
                throw new ArgumentException(
                    "An interop member name is required.", nameof(interopMemberName));
            }

            string key = interopMemberName.Trim();

            if (RemodelGuard.AllowedKeys.Contains(key, StringComparer.Ordinal))
            {
                return;
            }

            string member = CallKey.BareName(key);

            if (RemodelGuard.ExcludedMembers.Contains(member, StringComparer.OrdinalIgnoreCase))
            {
                throw new MutatingCallError(
                    key,
                    $"{key} is excluded from the stage-1 re-modeler surface by name "
                    + "(contracts/guard-allowlist.md).");
            }

            if (CallKey.IsQualified(key))
            {
                throw new MutatingCallError(
                    key,
                    $"{key} is not on the stage-1 re-modeler allowlist. The re-modeler's write "
                    + "surface is a closed set (contracts/guard-allowlist.md); stage 2 gets its "
                    + "own additive list.");
            }

            // A bare member name is a read call site, in the remodel family exactly as in the
            // reviewer's. The read-only rules apply to it unchanged.
            ReadOnlyGuard.Assert(key);
        }
    }
}
