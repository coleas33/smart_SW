using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
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

/// <summary>
/// Owner decision 151A (feature 011 T201, 2026-10-20; research R13.1, contracts/guard.md section 9): the three
/// allowlist guards answer through one shared rule, <see cref="AllowlistGuard"/>, where each wrote it in its
/// own code, and the tests read each guard's keys and bare-name policy through it rather than name each by its
/// type: the read audit's <c>Judged</c>, the creation tests' <c>AllowlistsByName</c> and the confirmed open's
/// read check. Each guard keeps its own list, its own words, its own construction site and its matching -
/// exact and ordinal - and <see cref="RemodelGuard"/>'s fourth answer stays its own. That no answer moved is
/// <see cref="AllowlistGuardAnswersTests"/>'.
/// </summary>
public class AllowlistGuardTests
{
    /// <summary>
    /// The product's allowlist guards are exactly the confirmed drawing's, the stage-1 re-modeler's and the
    /// pane seat's: of every guard a gate the product builds is built with (<see cref="GuardSweep.ProductGates"/>,
    /// which <see cref="GuardSweepTests"/> holds to every guard the product defines), these three are built on
    /// the shared rule, and the read-only guard and the two exemptions over it are not.
    /// </summary>
    [Fact]
    public void TheProductsAllowlistGuardsAreExactlyTheThree()
    {
        Assert.Equal(
            new[] { nameof(DrawingOpenGuard), nameof(RemodelGuard), nameof(RemodelSeatGuard) },
            GuardSweep.AllowlistGuards().Select(guard => guard.GetType().Name).OrderBy(name => name, StringComparer.Ordinal));
    }

    /// <summary>
    /// Each guard answers through the one shared <see cref="AllowlistGuard.Assert"/>: none declares an
    /// <c>Assert</c> of its own or implements <see cref="ICallGuard"/> again beside it, so the rule cannot
    /// differ guard by guard, and the shared one cannot be overridden.
    /// </summary>
    [Fact]
    public void EveryAllowlistGuardAnswersThroughTheOneSharedAssert()
    {
        MethodInfo shared = typeof(AllowlistGuard).GetMethod(nameof(AllowlistGuard.Assert))!;
        Assert.True(!shared.IsVirtual || shared.IsFinal, "AllowlistGuard.Assert can be overridden.");

        AllowlistGuard[] guards = GuardSweep.AllowlistGuards();
        Assert.NotEmpty(guards);
        foreach (AllowlistGuard guard in guards)
        {
            Type type = guard.GetType();
            InterfaceMapping map = type.GetInterfaceMap(typeof(ICallGuard));
            MethodInfo target = Assert.Single(map.TargetMethods);
            Assert.Equal(typeof(AllowlistGuard), target.DeclaringType);
            Assert.Equal(shared.MethodHandle, target.MethodHandle);
            Assert.Null(type.GetMethod(
                nameof(ICallGuard.Assert),
                BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly));
        }
    }

    /// <summary>
    /// Read through the shared rule, each guard's keys are its own list exactly - the set its class declares,
    /// to which its own tests pin it - and its bare names have its own policy: the confirmed drawing's and the
    /// stage-1's are the read-only guard's answer, with no reads of their own, and the pane seat's are its five
    /// reads alone. What the tests read is a copy: nothing done to it changes what a guard allows.
    /// </summary>
    [Fact]
    public void EachGuardsKeysAndBareNamePolicyAreItsOwn()
    {
        var guards = GuardSweep.AllowlistGuards().ToDictionary(guard => guard.GetType().Name, StringComparer.Ordinal);

        AssertSameSet(DrawingOpenGuard.AllowedKeys, guards[nameof(DrawingOpenGuard)].Keys);
        Assert.Equal(BareNamePolicy.ReadOnlyGuardsAnswer, guards[nameof(DrawingOpenGuard)].BareNames);
        Assert.Empty(guards[nameof(DrawingOpenGuard)].Reads);

        AssertSameSet(RemodelGuard.AllowedKeys, guards[nameof(RemodelGuard)].Keys);
        Assert.Equal(BareNamePolicy.ReadOnlyGuardsAnswer, guards[nameof(RemodelGuard)].BareNames);
        Assert.Empty(guards[nameof(RemodelGuard)].Reads);

        AssertSameSet(RemodelSeatGuard.AllowedKeys, guards[nameof(RemodelSeatGuard)].Keys);
        Assert.Equal(BareNamePolicy.OwnReadsOnly, guards[nameof(RemodelSeatGuard)].BareNames);
        AssertSameSet(RemodelSeatGuard.AllowedReads, guards[nameof(RemodelSeatGuard)].Reads);

        foreach (AllowlistGuard guard in guards.Values)
        {
            Assert.Throws<NotSupportedException>(() => ((ICollection<string>)guard.Keys).Add("IModelDoc2.EditDelete"));
            Assert.Throws<NotSupportedException>(() => ((ICollection<string>)guard.Reads).Add("CloseDoc"));
            Assert.Throws<MutatingCallError>(() => guard.Assert("IModelDoc2.EditDelete"));
        }
    }

    /// <summary>
    /// The shared rule, for each guard, read through its keys and its bare-name policy: each key passes, padded
    /// too, and in another case is refused naming it; a key of another guard, a read spelled qualified and a
    /// writer spelled qualified are refused naming them; a bare name is answered as the policy says - exactly
    /// the read-only guard's answer, or passed only if it is one of the guard's own reads and refused naming it
    /// otherwise - and a missing name is an argument error. The bare names: the reads the product makes, the
    /// bare names of every guard's keys, writers the read-only guard refuses and writers it leaves allowed, and
    /// a read in another case. <see cref="RemodelGuard"/>'s own refusals by name are the next test's.
    /// </summary>
    [Theory]
    [MemberData(nameof(AllowlistGuardAnswersTests.EveryAllowlistGuard), MemberType = typeof(AllowlistGuardAnswersTests))]
    public void EachGuardAnswersByTheSharedRuleItsKeysAndItsBareNamePolicy(string name)
    {
        AllowlistGuard guard = GuardSweep.AllowlistGuards().Single(each => each.GetType().Name == name);
        Assert.NotEmpty(guard.Keys);

        foreach (string key in guard.Keys)
        {
            guard.Assert(key);
            guard.Assert("  " + key + "  ");
            AssertRefusedNaming(guard, key.ToUpperInvariant());
            AssertRefusedNaming(guard, key.ToLowerInvariant());
        }

        IEnumerable<string> qualified = GuardSweep.AllowlistGuards()
            .SelectMany(other => other.Keys)
            .Except(guard.Keys, StringComparer.Ordinal)
            .Concat(new[] { "IModelDoc2.GetPathName", "IDrawingDoc.GetViews", "IModelDoc2.IsOpenedReadOnly", "IModelDoc2.EditDelete", "ISldWorks.OpenDoc" });
        foreach (string key in qualified)
        {
            AssertRefusedNaming(guard, key);
        }

        IEnumerable<string> bare = RemodelSeatGuard.AllowedReads
            .Concat(GuardSweep.AllowlistGuards().SelectMany(each => each.Keys).Select(CallKey.BareName))
            .Concat(new[] { "IsOpenedReadOnly", "GetDocuments", "GetViews", "GetTitle2", "Save3", "SaveAs3", "EditDelete", "DeleteConfiguration2", "SaveBMP", "getpathname" })
            .Distinct(StringComparer.Ordinal);
        foreach (string member in bare)
        {
            if (guard.BareNames == BareNamePolicy.ReadOnlyGuardsAnswer)
            {
                Assert.Equal(AllowlistGuardAnswersTests.Answer(ReadOnlyGuard.Assert, member), AllowlistGuardAnswersTests.Answer(guard.Assert, member));
            }
            else if (guard.Reads.Contains(member, StringComparer.Ordinal))
            {
                guard.Assert(member);
            }
            else
            {
                AssertRefusedNaming(guard, member);
            }
        }

        Assert.Throws<ArgumentException>(() => guard.Assert(null!));
        Assert.Throws<ArgumentException>(() => guard.Assert(string.Empty));
        Assert.Throws<ArgumentException>(() => guard.Assert("   "));
    }

    /// <summary>
    /// <see cref="RemodelGuard"/>'s fourth answer stays its own and explicit: a member it refuses by name - the
    /// undo stack's and undo recording's, which the read-only guard does not refuse - is refused bare, where its
    /// bare-name policy would hand it to the read-only guard and have it pass, in any case, and qualified with
    /// any interface, each in the exclusion's words rather than the words for a key off its list: its refusal by
    /// name is asked after its keys and before the rest of the shared rule. Neither other guard has it: the
    /// confirmed drawing's answers the bare name as the read-only guard does, and the pane seat's refuses it as
    /// a name off its list.
    /// </summary>
    [Fact]
    public void TheStage1GuardsFourthAnswerIsItsOwnRefusalByNameBeforeTheRestOfTheRule()
    {
        var stage1 = new RemodelGuard();
        Assert.NotEmpty(RemodelGuard.ExcludedMembers);
        foreach (string member in RemodelGuard.ExcludedMembers)
        {
            ReadOnlyGuard.Assert(member);
            foreach (string spelling in new[] { member, member.ToUpperInvariant(), "IModelDoc2." + member, "IModelDocExtension." + member })
            {
                MutatingCallError refusal = Assert.Throws<MutatingCallError>(() => stage1.Assert(spelling));
                Assert.Equal(spelling, refusal.MemberName);
                Assert.StartsWith(spelling + " is excluded from the stage-1 re-modeler surface by name", refusal.Message, StringComparison.Ordinal);
            }

            new DrawingOpenGuard().Assert(member);
            MutatingCallError seat = Assert.Throws<MutatingCallError>(() => new RemodelSeatGuard().Assert(member));
            Assert.DoesNotContain("excluded", seat.Message, StringComparison.Ordinal);
        }
    }

    private static void AssertRefusedNaming(ICallGuard guard, string name)
    {
        MutatingCallError refusal = Assert.Throws<MutatingCallError>(() => guard.Assert(name));
        Assert.Equal(name.Trim(), refusal.MemberName);
        Assert.Contains(name.Trim(), refusal.Message, StringComparison.Ordinal);
    }

    private static void AssertSameSet(IEnumerable<string> expected, IEnumerable<string> actual) =>
        Assert.Equal(
            expected.OrderBy(name => name, StringComparer.Ordinal),
            actual.OrderBy(name => name, StringComparer.Ordinal));
}
