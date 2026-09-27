using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.RegularExpressions;
using SwReview.Extractor.Rms;
using Xunit;

namespace SwReview.Extractor.Tests
{
    /// <summary>
    /// 004 T181 (default taken 2026-09-27, the owner may revise; research R15.1): the manifest
    /// command's reflection and its writer, over stand-in interfaces and enums declared below, so
    /// every rule - what a row reads, what refuses, how the file is spelt - is pinned without the
    /// real interop. <see cref="RemodelInteropManifestTests"/> holds the real fixture to the real
    /// interop through the same code.
    /// </summary>
    public class RemodelInteropManifestGenerationTests
    {
        private const string MembersNamespace = "SwReview.Extractor.Tests.InteropStandIns.Members";
        private const string ConstantsNamespace = "SwReview.Extractor.Tests.InteropStandIns.Constants";

        private static readonly DateTime At = new DateTime(2026, 9, 27, 12, 34, 56, DateTimeKind.Utc);

        private static readonly Assembly StandIns = typeof(RemodelInteropManifestGenerationTests).Assembly;

        private static readonly RemodelInteropAssemblies Interop =
            new RemodelInteropAssemblies(StandIns, MembersNamespace, StandIns, ConstantsNamespace);

        private static readonly RemodelInteropCall[] NoCalls = new RemodelInteropCall[0];
        private static readonly RemodelInteropConstants[] NoConstants = new RemodelInteropConstants[0];
        private static readonly RemodelInteropAbsence[] NoAbsences = new RemodelInteropAbsence[0];

        // ---- a row: what reflection answers, beside what the selection says ----------------------

        [Fact]
        public void AMethodRowReadsItsParametersInOrderItsByRefsAndItsReturnFromReflection()
        {
            // The builder's own spelling of the call is deliberately wrong in every reflected field:
            // the row is reflection's, never the table's.
            RemodelInteropManifestRow row = SingleRow(
                Call("IStandInDocument", "Activate", "property-get", "System.Void", "Wrong")
                    .WithUsedBy("remodel.open_copy", "remodel.plan")
                    .WithNote("a note, kept as written"));

            Assert.Equal("IStandInDocument.Activate", row.Key);
            Assert.Equal("method", row.Kind);
            Assert.Equal(
                new[] { "Name:System.String:False", "Rebuild:System.Boolean:False", "Errors:System.Int32&:True" },
                row.Parameters.Select(p => p.Name + ":" + p.Type + ":" + p.ByRef));
            Assert.Equal("System.Object", row.Returns);
            Assert.Equal(new[] { "remodel.open_copy", "remodel.plan" }, row.Selected.UsedBy);
            Assert.Equal("a note, kept as written", row.Selected.Note);
            Assert.Equal("(Name:System.String, Rebuild:System.Boolean, Errors:System.Int32&) -> System.Object", row.Signature);
        }

        [Theory]
        [InlineData("get_Title", "property-get", "() -> System.String")]
        [InlineData("set_Title", "property-set", "(value:System.String) -> System.Void")]
        [InlineData("get_Item", "property-get", "(Index:System.Int32) -> SwReview.Extractor.Tests.InteropStandIns.Members.IStandInFeature")]
        [InlineData("GetTitle", "method", "() -> System.String")]
        public void AKindIsAPropertysAccessorOnlyForASpecialGetOrSetName(string member, string kind, string signature)
        {
            RemodelInteropManifestRow row = SingleRow(Call("IStandInDocument", member).WithUsedBy("remodel.plan"));

            Assert.Equal(kind, row.Kind);
            Assert.Equal(signature, row.Signature);
        }

        /// <summary>A builder row is immutable: naming its commands or its note makes a new row.</summary>
        [Fact]
        public void WithUsedByAndWithNoteMakeNewCallsAndLeaveTheOriginalAsItWas()
        {
            RemodelInteropCall bare = Call("IStandInDocument", "Activate", "method", "System.Object", "Name", "Rebuild", "Errors");

            RemodelInteropCall used = bare.WithUsedBy("remodel.plan");
            RemodelInteropCall noted = used.WithNote("why");

            Assert.Empty(bare.UsedBy);
            Assert.Null(bare.Note);
            Assert.Equal(new[] { "remodel.plan" }, used.UsedBy);
            Assert.Null(used.Note);
            Assert.Equal(new[] { "remodel.plan" }, noted.UsedBy);
            Assert.Equal("why", noted.Note);
            Assert.All(new[] { used, noted }, call =>
            {
                Assert.Equal(bare.Key, call.Key);
                Assert.Equal(bare.Kind, call.Kind);
                Assert.Equal(bare.ParameterNames, call.ParameterNames);
                Assert.Equal(bare.Returns, call.Returns);
                Assert.Equal(bare.Allowlisted, call.Allowlisted);
            });
        }

        [Fact]
        public void TheRowsKeepTheSelectionsOrder()
        {
            RemodelInteropGeneration generation = RemodelInteropManifest.Generate(
                new[]
                {
                    Call("IStandInFeature", "get_Name").WithUsedBy("a"),
                    Call("IStandInDocument", "GetTitle").WithUsedBy("b"),
                    Call("IStandInDocument", "Activate").WithUsedBy("c"),
                },
                NoConstants,
                NoAbsences,
                Interop,
                At);

            Assert.True(generation.Succeeded, string.Join("; ", generation.Problems));
            Assert.Equal(
                new[] { "IStandInFeature.get_Name", "IStandInDocument.GetTitle", "IStandInDocument.Activate" },
                generation.Document.Members.Select(m => m.Key));
        }

        // ---- a row that cannot be read is a problem, and the manifest is not written -------------

        [Fact]
        public void AMissingInterfaceIsAProblemNamingTheRow()
        {
            RemodelInteropGeneration generation = Generate(Call("IGone", "Anything").WithUsedBy("remodel.open"));

            Assert.False(generation.Succeeded);
            Assert.Empty(generation.Document.Members);
            Assert.Contains("IGone is gone", Assert.Single(generation.Problems), StringComparison.Ordinal);
            Assert.Contains("(IGone.Anything)", generation.Problems[0], StringComparison.Ordinal);
        }

        [Fact]
        public void AMissingMemberIsAProblemAndTheOtherRowsAreStillRead()
        {
            RemodelInteropGeneration generation = RemodelInteropManifest.Generate(
                new[]
                {
                    Call("IStandInDocument", "Vanished").WithUsedBy("remodel.open"),
                    Call("IStandInDocument", "GetTitle").WithUsedBy("remodel.plan"),
                },
                NoConstants,
                NoAbsences,
                Interop,
                At);

            Assert.Equal("IStandInDocument.Vanished is gone from the installed SwReview.Extractor.Tests", Assert.Single(generation.Problems));
            Assert.Equal("IStandInDocument.GetTitle", Assert.Single(generation.Document.Members).Key);
        }

        [Fact]
        public void AnOverloadedMemberIsAProblemBecauseOneRowNoLongerIdentifiesIt()
        {
            RemodelInteropGeneration generation = Generate(Call("IStandInDocument", "Close").WithUsedBy("remodel.close"));

            Assert.Contains("IStandInDocument.Close has 2 overloads", Assert.Single(generation.Problems), StringComparison.Ordinal);
            Assert.Empty(generation.Document.Members);
        }

        [Fact]
        public void ARowWithNoUsedByIsAProblem()
        {
            RemodelInteropGeneration generation = Generate(Call("IStandInDocument", "GetTitle"));

            Assert.Equal(
                "IStandInDocument.GetTitle names no command in used_by; every row says who calls it",
                Assert.Single(generation.Problems));
        }

        [Fact]
        public void ARowWithABlankUsedByIsAProblem()
        {
            RemodelInteropGeneration generation = Generate(Call("IStandInDocument", "GetTitle").WithUsedBy("remodel.plan", " "));

            Assert.Contains("names no command in used_by", Assert.Single(generation.Problems), StringComparison.Ordinal);
        }

        [Fact]
        public void AMemberSelectedTwiceIsAProblem()
        {
            RemodelInteropGeneration generation = RemodelInteropManifest.Generate(
                new[]
                {
                    Call("IStandInDocument", "GetTitle").WithUsedBy("a"),
                    Call("IStandInDocument", "GetTitle").WithUsedBy("b"),
                },
                NoConstants,
                NoAbsences,
                Interop,
                At);

            Assert.Equal(
                "IStandInDocument.GetTitle is selected 2 times; a manifest has one row per member",
                Assert.Single(generation.Problems));
        }

        // ---- the constants -----------------------------------------------------------------------

        [Fact]
        public void EachConstantIsItsIntegerInTheSelectionsOrderNegativesIncluded()
        {
            RemodelInteropGeneration generation = RemodelInteropManifest.Generate(
                NoCalls,
                new[] { new RemodelInteropConstants("swStandIn_e", "swStandInLast", "swStandInFirst", "swStandInAll") },
                NoAbsences,
                Interop,
                At);

            Assert.True(generation.Succeeded, string.Join("; ", generation.Problems));
            RemodelInteropEnumRow row = Assert.Single(generation.Document.Enums);
            Assert.Equal("swStandIn_e", row.Name);
            Assert.Equal(
                new[] { "swStandInLast=4", "swStandInFirst=1", "swStandInAll=-1" },
                row.Values.Select(v => v.Key + "=" + v.Value));
        }

        [Fact]
        public void AMissingEnumAndAMissingConstantAreProblemsAndTheRestIsKept()
        {
            RemodelInteropGeneration generation = RemodelInteropManifest.Generate(
                NoCalls,
                new[]
                {
                    new RemodelInteropConstants("swGone_e", "swAnything"),
                    new RemodelInteropConstants("swStandIn_e", "swStandInFirst", "swStandInMissing"),
                    new RemodelInteropConstants("IStandInDocument", "NotAnEnum"),
                },
                NoAbsences,
                new RemodelInteropAssemblies(StandIns, MembersNamespace, StandIns, ConstantsNamespace),
                At);

            Assert.Equal(
                new[]
                {
                    "swGone_e is gone from the installed SwReview.Extractor.Tests",
                    "swStandIn_e.swStandInMissing is gone from the installed SwReview.Extractor.Tests",
                    "IStandInDocument is gone from the installed SwReview.Extractor.Tests",
                },
                generation.Problems);
            Assert.Equal(
                new[] { "swStandInFirst=1" },
                Assert.Single(generation.Document.Enums).Values.Select(v => v.Key + "=" + v.Value));
        }

        // ---- the absences ------------------------------------------------------------------------

        [Fact]
        public void AnAbsenceThatIsStillAbsentIsNoProblem()
        {
            RemodelInteropGeneration generation = RemodelInteropManifest.Generate(
                NoCalls,
                NoConstants,
                new[]
                {
                    RemodelInteropAbsence.OfMember("IStandInDocument", "set_GlobalVariable", "made by syntax"),
                    RemodelInteropAbsence.OfPattern("IStandInDocument", "*Shell*", "no creator", "GetShellType"),
                },
                Interop,
                At);

            Assert.True(generation.Succeeded, string.Join("; ", generation.Problems));
            Assert.Equal(2, generation.Document.Absences.Count);
        }

        [Fact]
        public void AMemberThatAppearedBreaksItsAbsence()
        {
            RemodelInteropGeneration generation = RemodelInteropManifest.Generate(
                NoCalls,
                NoConstants,
                new[] { RemodelInteropAbsence.OfMember("IStandInDocument", "GetTitle", "titles cannot be read") },
                Interop,
                At);

            Assert.Equal(
                "IStandInDocument.GetTitle was absent and is now present as GetTitle; the design depends on its "
                + "absence: titles cannot be read",
                Assert.Single(generation.Problems));
        }

        [Fact]
        public void APatternBreaksOnAnyNameThatHoldsItsCoreButTheExceptedOnes()
        {
            RemodelInteropGeneration generation = RemodelInteropManifest.Generate(
                NoCalls,
                NoConstants,
                new[] { RemodelInteropAbsence.OfPattern("IStandInDocument", "*Titl*", "no titles", "GetTitle") },
                Interop,
                At);

            Assert.Equal(
                "IStandInDocument.*Titl* was absent and is now present as Title, get_Title, set_Title; the design "
                + "depends on its absence: no titles",
                Assert.Single(generation.Problems));
        }

        [Fact]
        public void AnAbsenceOnAnInterfaceThatIsGoneCannotBeChecked()
        {
            RemodelInteropGeneration generation = RemodelInteropManifest.Generate(
                NoCalls, NoConstants, new[] { RemodelInteropAbsence.OfMember("IGone", "Name", "x") }, Interop, At);

            Assert.Equal("IGone is gone, so its recorded absence cannot be checked", Assert.Single(generation.Problems));
        }

        [Theory]
        [InlineData("*", "Anything", false)]
        [InlineData("**", "Anything", false)]
        [InlineData("Shell", "InsertShell", false)]
        [InlineData("*Shell", "InsertShell", false)]
        [InlineData("*Shell*", "InsertShell", true)]
        [InlineData("*Shell*", "GetPlasticsShellType", false)]
        [InlineData("*Shell*", "shell", false)]
        public void APatternIsAStarredCoreMatchedOrdinally(string pattern, string name, bool matches)
        {
            RemodelInteropAbsence absence = RemodelInteropAbsence.OfPattern("I", pattern, "c", "GetPlasticsShellType");

            Assert.Equal(matches, absence.Matches(name));
        }

        // ---- the header --------------------------------------------------------------------------

        [Theory]
        [InlineData(32, 5, "SOLIDWORKS 2024 SP5")]
        [InlineData(32, 0, "SOLIDWORKS 2024 SP0")]
        [InlineData(33, 1, "SOLIDWORKS 2025 SP1")]
        public void TheProductIsReadFromTheInteropVersion(int major, int minor, string product)
        {
            Assert.Equal(product, RemodelInteropManifest.ProductFor(new Version(major, minor, 0, 48)));
        }

        [Fact]
        public void AnInteropWithNoVersionIsAnUnknownProduct()
        {
            Assert.Equal("SOLIDWORKS (unknown version)", RemodelInteropManifest.ProductFor(null));
        }

        [Fact]
        public void TheHeaderNamesTheAssembliesTheCommandAndTheSecondItRan()
        {
            RemodelInteropManifestDocument document = RemodelInteropManifest.Generate(
                NoCalls, NoConstants, NoAbsences, Interop, new DateTime(2026, 9, 27, 12, 34, 56, 789, DateTimeKind.Utc)).Document;

            Assert.Equal("1.0", document.Schema);
            Assert.Equal("SwReview.Extractor.Tests", document.Assembly);
            Assert.Equal(StandIns.GetName().Version!.ToString(), document.AssemblyVersion);
            Assert.Equal(StandIns.GetName().Version!.ToString(), document.SwconstVersion);
            Assert.Equal(RemodelInteropManifest.ProductFor(StandIns.GetName().Version), document.Product);
            Assert.Equal("swreview-extract probe interop --emit-manifest", document.GeneratedBy);
            Assert.Equal(At, document.GeneratedAt);
            Assert.Equal(DateTimeKind.Utc, document.GeneratedAt.Kind);
        }

        [Fact]
        public void ALocalTimeIsWrittenInUtc()
        {
            DateTime local = At.ToLocalTime();

            Assert.Equal(At, RemodelInteropManifest.Generate(NoCalls, NoConstants, NoAbsences, Interop, local).Document.GeneratedAt);
        }

        // ---- the file ----------------------------------------------------------------------------

        /// <summary>
        /// The fixture's own format, whole: two-space indentation, the key order, <c>by_ref</c> only
        /// when true, a note only when there is one, <c>member</c> or <c>member_pattern</c> and
        /// <c>except</c> only when there are exceptions, quotes and apostrophes as the fixture spells
        /// them, LF line ends and one final newline.
        /// </summary>
        [Fact]
        public void TheFileIsWrittenInTheFixturesFormat()
        {
            RemodelInteropGeneration generation = RemodelInteropManifest.Generate(
                new[]
                {
                    Call("IStandInDocument", "Activate").WithUsedBy("remodel.open_copy").WithNote("the copy's 'title', \"quoted\""),
                    Call("IStandInDocument", "GetTitle").WithUsedBy("remodel.plan", "remodel.start"),
                },
                new[] { new RemodelInteropConstants("swStandIn_e", "swStandInFirst", "swStandInAll") },
                new[]
                {
                    RemodelInteropAbsence.OfMember("IStandInDocument", "set_GlobalVariable", "by \"syntax\""),
                    RemodelInteropAbsence.OfPattern("IStandInDocument", "*Shell*", "none", "GetShellType"),
                },
                Interop,
                At);
            Assert.True(generation.Succeeded, string.Join("; ", generation.Problems));

            string version = StandIns.GetName().Version!.ToString();
            string expected = string.Join(
                "\n",
                "{",
                "  \"manifest_schema\": \"1.0\",",
                "  \"assembly\": \"SwReview.Extractor.Tests\",",
                "  \"assembly_version\": \"" + version + "\",",
                "  \"swconst_version\": \"" + version + "\",",
                "  \"product\": \"" + RemodelInteropManifest.ProductFor(StandIns.GetName().Version) + "\",",
                "  \"generated_at\": \"2026-09-27T12:34:56Z\",",
                "  \"generated_by\": \"swreview-extract probe interop --emit-manifest\",",
                "  \"members\": [",
                "    {",
                "      \"interface\": \"IStandInDocument\",",
                "      \"member\": \"Activate\",",
                "      \"kind\": \"method\",",
                "      \"arity\": 3,",
                "      \"parameters\": [",
                "        {",
                "          \"name\": \"Name\",",
                "          \"type\": \"System.String\"",
                "        },",
                "        {",
                "          \"name\": \"Rebuild\",",
                "          \"type\": \"System.Boolean\"",
                "        },",
                "        {",
                "          \"name\": \"Errors\",",
                "          \"type\": \"System.Int32&\",",
                "          \"by_ref\": true",
                "        }",
                "      ],",
                "      \"returns\": \"System.Object\",",
                "      \"used_by\": [",
                "        \"remodel.open_copy\"",
                "      ],",
                "      \"allowlisted\": false,",
                "      \"note\": \"the copy's 'title', \\\"quoted\\\"\"",
                "    },",
                "    {",
                "      \"interface\": \"IStandInDocument\",",
                "      \"member\": \"GetTitle\",",
                "      \"kind\": \"method\",",
                "      \"arity\": 0,",
                "      \"parameters\": [],",
                "      \"returns\": \"System.String\",",
                "      \"used_by\": [",
                "        \"remodel.plan\",",
                "        \"remodel.start\"",
                "      ],",
                "      \"allowlisted\": false",
                "    }",
                "  ],",
                "  \"enums\": [",
                "    {",
                "      \"enum\": \"swStandIn_e\",",
                "      \"values\": {",
                "        \"swStandInFirst\": 1,",
                "        \"swStandInAll\": -1",
                "      }",
                "    }",
                "  ],",
                "  \"absences\": [",
                "    {",
                "      \"interface\": \"IStandInDocument\",",
                "      \"member\": \"set_GlobalVariable\",",
                "      \"consequence\": \"by \\\"syntax\\\"\"",
                "    },",
                "    {",
                "      \"interface\": \"IStandInDocument\",",
                "      \"member_pattern\": \"*Shell*\",",
                "      \"except\": [",
                "        \"GetShellType\"",
                "      ],",
                "      \"consequence\": \"none\"",
                "    }",
                "  ]",
                "}",
                string.Empty);

            Assert.Equal(expected, RemodelInteropManifest.Write(generation.Document));
        }

        [Fact]
        public void AnAllowlistedRowSaysSo()
        {
            RemodelInteropManifestRow row = SingleRow(
                new RemodelInteropCall("IStandInDocument", "GetTitle", "method", new string[0], "System.String", true)
                    .WithUsedBy("remodel.plan"));

            Assert.Contains("\"allowlisted\": true", RemodelInteropManifest.Write(Document(row)), StringComparison.Ordinal);
        }

        // ---- the redist folder -------------------------------------------------------------------

        [Theory]
        [InlineData(null)]
        [InlineData("")]
        [InlineData("   ")]
        public void ABlankRedistFolderIsNoInterop(string? folder)
        {
            Assert.Null(RemodelInteropAssemblies.FromRedist(folder));
        }

        [Fact]
        public void ARedistFolderWithoutBothAssembliesIsNoInterop()
        {
            string onlyOne = Path.Combine(Path.GetTempPath(), "swreview-redist-one-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(onlyOne);
            try
            {
                File.WriteAllText(Path.Combine(onlyOne, "SolidWorks.Interop.sldworks.dll"), string.Empty);

                Assert.Null(RemodelInteropAssemblies.FromRedist(onlyOne));
                Assert.Null(RemodelInteropAssemblies.FromRedist(Path.Combine(onlyOne, "missing")));
            }
            finally
            {
                Directory.Delete(onlyOne, recursive: true);
            }
        }

        /// <summary>
        /// The test host's folder holds a copy of both interops (the test project references them
        /// with <c>Private=true</c>), so it reads as a redist folder on any machine that built this.
        /// </summary>
        [Fact]
        public void ARedistFolderWithBothAssembliesIsReadForItsMetadata()
        {
            RemodelInteropAssemblies? interop = RemodelInteropAssemblies.FromRedist(AppContext.BaseDirectory);

            Assert.NotNull(interop);
            Assert.Equal("SolidWorks.Interop.sldworks", interop!.SldWorks.GetName().Name);
            Assert.Equal("SolidWorks.Interop.swconst", interop.SwConst.GetName().Name);
            Assert.Equal("SolidWorks.Interop.sldworks", interop.SldWorksNamespace);
            Assert.Equal("SolidWorks.Interop.swconst", interop.SwConstNamespace);
        }

        // ---- metadata only -----------------------------------------------------------------------

        /// <summary>
        /// Nothing the command runs can make a COM object or reach SOLIDWORKS: no activation, no
        /// running-object lookup, no late-bound invoke and no attach, in the generator or in the
        /// console command around it.
        /// </summary>
        [Theory]
        [InlineData("SwReview.Extractor/Rms/RemodelInteropManifest.cs")]
        [InlineData("SwReview.Extractor.Console/InteropManifestProbe.cs")]
        public void TheCommandReadsMetadataAndNeverMakesACOMObject(string relative)
        {
            string file = Path.Combine(
                new[] { DrawingFamilyReadAuditTests.ExtractorRoot() }.Concat(relative.Split('/')).ToArray());
            string code = RemodelInteropManifestTests.InteropMemberScan.CodeOnly(File.ReadAllText(file));

            foreach (string forbidden in new[]
                     {
                         "Activator", "CreateInstance", "GetTypeFromProgID", "GetTypeFromCLSID", "GetActiveObject",
                         "InvokeMember", ".Invoke(", "SwAttach", "Connect(", "ISldWorks", "SldWorks(",
                     })
            {
                Assert.DoesNotContain(forbidden, code, StringComparison.Ordinal);
            }

            Assert.Matches(new Regex(@"\bGetMethods\(|\bGenerate\("), code);
        }

        // ---- helpers -----------------------------------------------------------------------------

        private static RemodelInteropCall Call(
            string interfaceName, string member, string kind = "method", string returns = "System.Object", params string[] parameters) =>
            new RemodelInteropCall(interfaceName, member, kind, parameters, returns, allowlisted: false);

        private static RemodelInteropGeneration Generate(RemodelInteropCall call) =>
            RemodelInteropManifest.Generate(new[] { call }, NoConstants, NoAbsences, Interop, At);

        private static RemodelInteropManifestRow SingleRow(RemodelInteropCall call)
        {
            RemodelInteropGeneration generation = Generate(call);
            Assert.True(generation.Succeeded, string.Join("; ", generation.Problems));
            return Assert.Single(generation.Document.Members);
        }

        private static RemodelInteropManifestDocument Document(RemodelInteropManifestRow row) =>
            new RemodelInteropManifestDocument(
                "a", "1", "1", "p", At, new[] { row }, new RemodelInteropEnumRow[0], NoAbsences);
    }
}

namespace SwReview.Extractor.Tests.InteropStandIns.Members
{
    /// <summary>A stand-in interop interface: a method with a ByRef, properties, an indexer and an overload.</summary>
    public interface IStandInDocument
    {
        string Title { get; set; }

        IStandInFeature this[int Index] { get; }

        object Activate(string Name, bool Rebuild, ref int Errors);

        string GetTitle();

        void Close(string Name);

        void Close(string Name, bool Save);
    }

    /// <summary>A second stand-in, so a row's order is the selection's and not an interface's.</summary>
    public interface IStandInFeature
    {
        string Name { get; }
    }
}

namespace SwReview.Extractor.Tests.InteropStandIns.Constants
{
    /// <summary>A stand-in swconst enum, declared out of value order and with a negative member.</summary>
    public enum swStandIn_e
    {
        swStandInAll = -1,
        swStandInFirst = 1,
        swStandInLast = 4,
    }
}
